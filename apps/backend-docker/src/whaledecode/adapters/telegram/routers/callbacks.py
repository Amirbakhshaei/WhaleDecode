import structlog
from aiogram import Router, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from html import escape

from whaledecode.adapters.telegram.routers.chat import _spend_quota
from whaledecode.adapters.telegram.user_access import get_or_create_user
from whaledecode.domain.exceptions import PlanLimitError

log = structlog.get_logger()
callback_router = Router(name="callbacks")


def alert_keyboard(alert_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="Explain more", callback_data=f"alert:{alert_id}:explain")],
        [
            InlineKeyboardButton(text="Risks", callback_data=f"alert:{alert_id}:risks"),
            InlineKeyboardButton(text="Related", callback_data=f"alert:{alert_id}:related"),
        ],
        [InlineKeyboardButton(text="Ask follow-up", callback_data=f"alert:{alert_id}:follow")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@callback_router.callback_query(lambda c: c.data and c.data.startswith("alert:"))
async def handle_alert_callback(callback: types.CallbackQuery, uow_factory, investigation_service, **kwargs) -> None:
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("Invalid callback.")
        return

    alert_id = parts[1]
    action = parts[2]
    user_id = callback.from_user.id

    await callback.answer()

    async with uow_factory() as uow:
        user = await get_or_create_user(user_id, callback.from_user.username, uow)
        alerts = await uow.alerts.list_by_user(user.id, limit=1)
        if not alerts:
            await callback.message.answer("Alert not found.")
            return
        alert = alerts[0]
        event = await uow.candidate_events.get(alert.event_id)

    if action == "risks":
        if event:
            await callback.message.answer(
                f"⚠️ <b>Risk Analysis</b>\n\nEvent score: {event.score:.1f}\n\n"
                "Large value transfers carry market impact risk. "
                "Always DYOR before making decisions."
            )
        else:
            await callback.message.answer("Event details not available.")
    elif action == "explain":
        context = f"Explain more about alert {alert_id}"
        resp = await investigation_service.chat(context)
        await callback.message.answer(resp[:4000])
    elif action == "related":
        context = f"Find related transactions and activity for alert {alert_id}"
        resp = await investigation_service.chat(context)
        await callback.message.answer(resp[:4000])
    elif action == "follow":
        await callback.message.answer(
            "What would you like to know more about? Type your question below."
        )
    else:
        await callback.message.answer("Unknown action.")


@callback_router.callback_query(lambda c: c.data and c.data.startswith("act:"))
async def handle_hub_actions(
    callback: types.CallbackQuery,
    uow_factory,
    investigation_service,
    wallet_service,
    settings=None,
    **kwargs,
) -> None:
    """Intelligence Hub button handler (tx_/wallet_ deep-link menus).

    Address-bound actions (track/port/chatw) arrive here as callbacks; tx-hash
    actions are URL deep links handled by cmd_start.
    """
    if not callback.data:
        await callback.answer("Invalid action.")
        return
    try:
        _, action, chain, ref = callback.data.split(":", 3)
    except ValueError:
        await callback.answer("Invalid action.")
        return

    await callback.answer()
    user_id = callback.from_user.id

    if action == "track":
        async with uow_factory() as uow:
            user = await get_or_create_user(user_id, callback.from_user.username, uow)
            curated = await uow.curated_wallets.get_by_address_and_chain(ref, chain)
            if curated is None:
                await callback.message.answer(
                    "🕵️ This address isn't in the curated watchlist yet, so I can't "
                    f"auto-track it. You can still ask about it with <code>/ask {escape(ref)}</code>."
                )
                return
            tracked = await uow.tracked_wallets.list_by_user(user.id)
            is_tracked = any(t.wallet_id == curated.id and t.is_active for t in tracked)
        try:
            if is_tracked:
                await wallet_service.untrack(user.id, curated.id)
                status = f"✅ Stopped tracking <b>{escape(curated.label)}</b>."
            else:
                await wallet_service.track(user.id, curated.id, curated.chain.name)
                status = (
                    f"🔔 Now tracking <b>{escape(curated.label)}</b> "
                    f"({curated.address[:6]}…{curated.address[-4:]})."
                )
        except PlanLimitError as e:
            status = f"⚠️ {escape(str(e))}"
        await callback.message.answer(status)
        return

    if action == "chatw":
        if not await _spend_quota(callback.message, uow_factory, settings):
            return
        await callback.message.answer("🧠 Investigating wallet...")
        try:
            result = await investigation_service.chat(
                f"Investigate this wallet: {ref}", thread_id=str(user_id)
            )
            await callback.message.answer(result[:4000])
            await callback.message.answer("💬 Ask follow-up questions about this wallet below.")
        except Exception as e:  # noqa: BLE001
            await callback.message.answer(f"Sorry, I encountered an error: {escape(str(e)[:200])}")
        return

    if action == "port":
        if not await _spend_quota(callback.message, uow_factory, settings):
            return
        await callback.message.answer("🧠 Building portfolio breakdown...")
        try:
            result = await investigation_service.chat(
                f"Give a portfolio breakdown for this wallet: {ref}", thread_id=str(user_id)
            )
            await callback.message.answer(result[:4000])
        except Exception as e:  # noqa: BLE001
            await callback.message.answer(f"Sorry, I encountered an error: {escape(str(e)[:200])}")
        return

    await callback.message.answer("Unknown action.")


@callback_router.callback_query(lambda c: c.data and c.data.startswith("swapsel:"))
async def handle_swap_selection(callback: types.CallbackQuery, settings=None, **kwargs) -> None:
    """Module 4 execution: user picked an amount -> live 0x Swap API v2 quote.

    Runs strictly on-demand (user tap), never on the alert critical path. The
    0.8% protocol fee is embedded in the quote via swapFeeBps/swapFeeRecipient;
    execution happens in the user's own wallet via Permit2 — we stay
    non-custodial end to end.
    """
    from whaledecode.adapters.zerox.client import ZeroXClient, wei
    from whaledecode.services.swap_router import DEFAULT_FEE_BPS

    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        await callback.answer("Invalid swap selection.")
        return
    _, amount_str, chain_code, token = parts
    try:
        amount_eth = float(amount_str)
    except ValueError:
        await callback.answer("Invalid amount.")
        return

    chain = {"ETH": "ethereum", "BASE": "base", "ARB": "arbitrum"}.get(chain_code.upper(), "base")
    fee_recipient = settings.SWAP_FEE_RECIPIENT if settings else ""
    fee_bps = int(getattr(settings, "SWAP_FEE_BPS", DEFAULT_FEE_BPS)) if settings else DEFAULT_FEE_BPS

    await callback.answer("Fetching 0x quote…")
    client = ZeroXClient.from_settings(settings) if settings else ZeroXClient("")
    quote = await client.quote(
        chain,
        token,
        wei(amount_eth),
        fee_recipient_bps=(fee_recipient, fee_bps) if fee_recipient else None,
    )
    buy_amount_wei = quote.get("buyAmount") or quote.get("grossBuyAmount") or ""
    lines = [
        f"🛒 <b>0x v2 Quote</b> — Buy for {amount_eth:g} ETH",
        f"🪙 Token: <code>{token[:16]}…{token[-6:]}</code>",
        f"🏦 Protocol fee: {fee_bps / 100:.1f}% (included)",
    ]
    markup = None
    tx_to = quote.get("transaction", {}).get("data") if isinstance(quote.get("transaction"), dict) else None
    if buy_amount_wei:
        # Token decimals are unknown here; show raw units + the deterministic
        # Matcha fallback where the wallet completes execution.
        lines.append(f"📦 Expected out: <code>{int(buy_amount_wei):,}</code> base units (pre-decimals)")
    if tx_to:
        lines.append("✅ Quote ready — open it on Matcha to execute with your connected wallet.")
    from whaledecode.services.swap_router import build_swap_links

    links = build_swap_links(chain, token, fee_recipient=fee_recipient, fee_bps=fee_bps)
    if links:
        execute_url = links.get("⚡ Custom Swap") or next(iter(links.values()))
        markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🛒 Execute Swap", url=execute_url)]]
        )
    await callback.message.answer("\n".join(lines), reply_markup=markup)
