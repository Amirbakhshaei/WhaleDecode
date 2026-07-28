from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from whaledecode.adapters.telegram.user_access import get_or_create_user

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
        "I monitor smart-money wallets and alert you to interesting on-chain activity.\n\n"
        "Commands:\n"
        "<code>/wallets</code> — browse curated wallets\n"
        "<code>/track &lt;id&gt;</code> — track a wallet\n"
        "<code>/untrack &lt;id&gt;</code> — stop tracking\n"
        "<code>/chat &lt;question&gt;</code> — ask the AI agent\n"
        "<code>/alerts</code> — view your alerts\n"
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
        "Commands:\n"
        "<code>/wallets</code> — browse curated wallets\n"
        "<code>/track &lt;id&gt;</code> — track a wallet\n"
        "<code>/untrack &lt;id&gt;</code> — stop tracking\n"
        "<code>/chat &lt;question&gt;</code> — ask the AI agent\n"
        "<code>/alerts</code> — view your alerts\n"
        "<code>/help</code> — this message"
    )
