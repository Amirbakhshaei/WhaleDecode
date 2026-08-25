from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from whaledecode.adapters.telegram.keyboards import (
    _chain_code,
    build_tx_action_hub,
    build_wallet_dossier_hub,
)
from whaledecode.adapters.telegram.user_access import get_or_create_user
from whaledecode.application.services.user_service import (
    UPGRADE_CTA_MESSAGE,
    check_and_decrement_quota,
)
from whaledecode.config.tiers import PLAN_LIMITS, PlanTier, get_limits
from whaledecode.domain.exceptions import QuotaExceededError

common_router = Router(name="common")


def build_swap_amount_keyboard(token: str, chain_code: str = "BASE") -> InlineKeyboardMarkup:
    """Quick-amount picker for the ``swap_{token}`` deep-link flow.

    callback_data carries the full token address (chain code + amount + 42-char
    address ≈ 57 bytes, within Telegram's 64-byte limit); the selected amount
    triggers an on-demand 0x v2 quote in the callback handler.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⚡ Buy 0.1 ETH", callback_data=f"swapsel:0.1:{chain_code}:{token}"),
                InlineKeyboardButton(text="⚡ Buy 0.5 ETH", callback_data=f"swapsel:0.5:{chain_code}:{token}"),
            ],
            [
                InlineKeyboardButton(text="⚡ Buy 1 ETH", callback_data=f"swapsel:1:{chain_code}:{token}"),
            ],
        ]
    )


@common_router.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject, uow_factory, investigation_service=None, settings=None, **kwargs) -> None:
    async with uow_factory() as uow:
        user = await get_or_create_user(message.from_user.id, message.from_user.username, uow)
        await uow.commit()

    admin_ids = settings.ADMIN_USER_IDS if settings else []
    payload = (command.args or "").strip()

    async def _resolve_event_ref(ref: str) -> tuple[str, str, dict] | None:
        """Resolve a deep-link reference to (chain_code, tx_hash, raw_json).

        New links carry the candidate_events id (Telegram caps ?start= at 64
        bytes, a raw hash exceeds that); legacy links carry the hash itself.
        """
        if ref.isdigit():
            async with uow_factory() as uow:
                event = await uow.candidate_events.get(int(ref))
            if event is None:
                return None
            raw = event.raw_json if isinstance(event.raw_json, dict) else {}
            return _chain_code(str(event.chain)), str(event.tx_hash), raw
        return None

    if payload:
        # New Intelligence Hub deep links: present an inline action menu instead of
        # executing a fixed command. tx-hash actions are URL deep links (the hash
        # exceeds callback_data's 64-byte limit); wallet actions use callbacks.
        if payload.startswith("tx_"):
            parts = payload.split("_", 2)
            chain_code = parts[1] if len(parts) > 2 else "ETH"
            ref = parts[-1]
            resolved = await _resolve_event_ref(ref)
            if resolved is not None:
                chain, tx_hash, raw = resolved
                event_id = int(ref)
                from_addr = str(raw.get("from", ""))
                token_address = str(raw.get("address", ""))
            else:
                chain, tx_hash = chain_code, ref
                event_id, from_addr, token_address = None, "", ""
            await message.answer(
                f"⚡ <b>WhaleDecode Intelligence Hub</b>\n\n"
                f"🔗 Chain: <code>{chain.upper()}</code>\n"
                f"📜 Tx: <code>{tx_hash[:12]}…{tx_hash[-8:]}</code>\n\n"
                f"👇 Choose an investigation action:",
                reply_markup=build_tx_action_hub(
                    chain, tx_hash, event_id=event_id,
                    from_addr=from_addr, token_address=token_address,
                ),
            )
            return

        if payload.startswith("wallet_"):
            parts = payload.split("_", 2)
            chain = parts[1] if len(parts) > 2 else "ETH"
            wallet = parts[-1].lower()
            await message.answer(
                f"👤 <b>Wallet Dossier Hub</b>\n\n"
                f"🔗 Chain: <code>{chain.upper()}</code>\n"
                f"👛 Address: <code>{wallet}</code>\n\n"
                f"Select an action to inspect or monitor this entity:",
                reply_markup=build_wallet_dossier_hub(chain, wallet),
            )
            return

        # Module 4: swap_{token_address} (optionally swap_{chain}_{token}) —
        # one-click execution entry point from a channel purchase alert. The
        # quote itself is fetched on demand when the user picks an amount,
        # never during this handler.
        if payload.startswith("swap_"):
            from whaledecode.adapters.zerox.client import chain_id as zerox_chain_id

            parts = payload.split("_")
            if len(parts) == 2:
                chain, token = "base", parts[1].lower()
            else:
                chain, token = parts[1].lower(), parts[-1].lower()
            code = {"eth": "ETH", "ethereum": "ETH", "base": "BASE", "arb": "ARB", "arbitrum": "ARB"}.get(chain, "BASE")
            supported = bool(zerox_chain_id(chain))
            note = "" if supported else "\n⚠️ Live quotes unavailable on this chain — links only."
            await message.answer(
                f"🛒 <b>1-Click Swap</b>\n\n"
                f"🔗 Chain: <code>{chain.upper()}</code>\n"
                f"🪙 Token: <code>{token[:16]}…{token[-6:]}</code>{note}\n\n"
                f"Pick an amount for a live 0x quote:",
                reply_markup=build_swap_amount_keyboard(token, code),
            )
            return

        # Channel / legacy deep links: ?start=deepdive_<chain>_<tx> / ask_<chain>_<tx> /
        # net_<chain>_<tx> / track_<chain>_<addr>; intra-platform: analyze_<tx>.
        # deepdive_/ask_/net_ → on-chain event analysis; track_ → a chat prompt about
        # that entity (one-tap address tracking is not wired into WalletService yet).
        parts = payload.split("_")
        action = parts[0]
        chain = parts[1] if len(parts) > 2 else "ETH"
        target = parts[-1]
        resolved = await _resolve_event_ref(target)
        if resolved is not None:
            chain, target, _ = resolved
        if action == "track":
            prompt = f"Analyze and describe this wallet: {target}"
        elif action == "net":
            prompt = f"Map the counterparty network for this on-chain event ({chain}): {target}"
        elif action in ("analyze", "deepdive", "ask"):
            prompt = f"Deep dive into this on-chain event ({chain}): {target}"
        else:
            prompt = f"Deep dive into this on-chain event: {payload}"
        if investigation_service is None:
            await message.answer("Investigation service unavailable.")
            return
        # Admin IDs bypass the free-tier quota so operators are never blocked.
        if message.from_user.id not in admin_ids:
            try:
                async with uow_factory() as uow:
                    await check_and_decrement_quota(uow, message.from_user.id, admin_ids=admin_ids)
                    await uow.commit()
            except QuotaExceededError:
                await message.answer(UPGRADE_CTA_MESSAGE)
                return
        await message.answer("🧠 Investigating the on-chain event...")
        try:
            result = await investigation_service.chat(
                prompt,
                thread_id=str(message.from_user.id),
            )
            await message.answer(result[:4000])
        except Exception as e:  # noqa: BLE001
            await message.answer(f"Sorry, I encountered an error: {e}")
        return

    plan_badge = "⭐ FREE" if user.plan == "free" else "💎 PAID"
    await message.answer(
        f"🐋 <b>WhaleDecode</b>\n\n"
        f"Welcome{', ' + user.username if user.username else ''}! "
        f"Plan: {plan_badge}\n\n"
        "I monitor smart-money wallets on Base and Arbitrum and alert you to interesting on-chain activity.\n\n"
        "<b>🚀 Quickstart (3 steps):</b>\n"
        "1️⃣ Tap a whale alert in our channel → the Intelligence Hub opens\n"
        "2️⃣ Pick <b>🔬 Run Full Deep Dive</b> for an instant AI investigation\n"
        "3️⃣ Ask follow-ups with <code>/ask</code> — I remember your thread\n\n"
        "<b>Example whale addresses to try:</b>\n"
        "<code>/ask What is vitalik.eth doing?</code>\n"
        "<code>/decode 0x2e07ab7c67f4a0b8e83d3e9f5a6b1c4d8e9f0a1b2c3d4e5f60718293a4b5c6d7</code>\n\n"
        "Commands:\n"
        "<code>/ask &lt;question&gt;</code> — ask about a wallet, token, or tx\n"
        "<code>/decode &lt;tx&gt;</code> — decode a transaction\n"
        "<code>/wallets</code> — browse curated wallets\n"
        "<code>/track &lt;id&gt;</code> — track a curated wallet\n"
        "<code>/untrack &lt;id&gt;</code> — stop tracking\n"
        "<code>/alerts [on|off]</code> — manage alerts\n"
        "<code>/briefing</code> — daily briefing\n"
        "<code>/status</code> — your plan and usage\n"
        "<code>/upgrade</code> — plan details\n"
        "<code>/help</code> — this message"
    )


@common_router.message(Command("help"))
async def cmd_help(message: Message, uow_factory, **kwargs) -> None:
    async with uow_factory() as uow:
        user = await get_or_create_user(message.from_user.id, message.from_user.username, uow)
    plan_badge = "⭐ FREE" if user.plan == "free" else "💎 PAID"
    await message.answer(
        f"🐋 <b>WhaleDecode</b>\n\n"
        f"Plan: {plan_badge}\n\n"
        "I monitor smart-money wallets and alert you to interesting on-chain activity.\n\n"
        "Commands:\n"
        "<code>/ask &lt;question&gt;</code> — ask a question\n"
        "<code>/decode &lt;tx&gt;</code> — decode a transaction\n"
        "<code>/wallets</code> — browse curated wallets\n"
        "<code>/track &lt;id&gt;</code> — track a wallet\n"
        "<code>/untrack &lt;id&gt;</code> — stop tracking\n"
        "<code>/alerts [on|off]</code> — manage alerts\n"
        "<code>/briefing</code> — daily briefing\n"
        "<code>/status</code> — your plan\n"
        "<code>/upgrade</code> — upgrade info\n"
        "<code>/help</code> — this message"
    )


@common_router.message(Command("status"))
async def cmd_status(message: Message, uow_factory, **kwargs) -> None:
    async with uow_factory() as uow:
        user = await get_or_create_user(message.from_user.id, message.from_user.username, uow)
        tracked = await uow.tracked_wallets.count_active_by_user(user.id)
        limits = get_limits(user.plan)
    plan_badge = "⭐ FREE" if user.plan == "free" else "💎 PAID"
    alerts_status = "enabled" if user.alerts_enabled else "disabled"
    await message.answer(
        f"<b>Your Status</b>\n\n"
        f"Plan: {plan_badge}\n"
        f"Chats used: {user.daily_chat_count}/{limits.chat_per_day} today\n"
        f"Tracked wallets: {tracked}/{limits.max_tracked_wallets}\n"
        f"Alerts: {alerts_status}\n"
        f"Alert delivery: {limits.alert_immediacy}"
    )


@common_router.message(Command("upgrade"))
async def cmd_upgrade(message: Message, **kwargs) -> None:
    free = PLAN_LIMITS[PlanTier.FREE]
    paid = PLAN_LIMITS[PlanTier.PAID]
    await message.answer(
        "<b>Plans</b>\n\n"
        "⭐ <b>Free</b>\n"
        f"• {free.chat_per_day} chats/day\n"
        f"• {free.max_tracked_wallets} tracked wallets\n"
        f"• {free.alert_immediacy} alerts\n\n"
        "💎 <b>Paid</b>\n"
        f"• {paid.chat_per_day} chats/day\n"
        f"• up to {paid.max_tracked_wallets} tracked wallets\n"
        f"• {paid.alert_immediacy} alerts\n"
        f"• on-demand briefings\n\n"
        "To upgrade, contact @admin."
    )
