from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from whaledecode.adapters.telegram.user_access import get_or_create_user
from whaledecode.config.tiers import PLAN_LIMITS, PlanTier, get_limits

common_router = Router(name="common")


@common_router.message(Command("start"))
async def cmd_start(message: Message, uow_factory, **kwargs) -> None:
    async with uow_factory() as uow:
        user = await get_or_create_user(message.from_user.id, message.from_user.username, uow)
    plan_badge = "⭐ FREE" if user.plan == "free" else "💎 PAID"
    await message.answer(
        f"🐋 <b>WhaleDecode</b>\n\n"
        f"Welcome{', ' + user.username if user.username else ''}! "
        f"Plan: {plan_badge}\n\n"
        "I monitor smart-money wallets on Base and Arbitrum and alert you to interesting on-chain activity.\n\n"
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
