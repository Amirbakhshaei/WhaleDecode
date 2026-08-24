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
