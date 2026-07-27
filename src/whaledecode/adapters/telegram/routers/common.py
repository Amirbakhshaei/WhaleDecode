from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.domain.entities.user import User

common_router = Router(name="common")


async def _get_or_create_user(message: Message, uow: UnitOfWork) -> User:
    tg_id = message.from_user.id
    existing = await uow.users.get_by_tg_id(tg_id)
    if existing:
        return existing
    user = User(
        tg_id=tg_id,
        username=message.from_user.username,
        plan="free",
    )
    created = await uow.users.create(user)
    await uow.commit()
    return created


@common_router.message(Command("start"))
async def cmd_start(message: Message, uow_factory, **kwargs) -> None:
    async with uow_factory() as uow:
        user = await _get_or_create_user(message, uow)
    plan_badge = "⭐ FREE" if user.plan == "free" else "💎 PAID"
    await message.answer(
        f"🐋 *WhaleDecode*\n\n"
        f"Welcome{', ' + user.username if user.username else ''}! "
        f"Plan: {plan_badge}\n\n"
        "I monitor smart-money wallets and alert you to interesting on-chain activity.\n\n"
        "Commands:\n"
        "`/wallets` — browse curated wallets\n"
        "`/track <id>` — track a wallet\n"
        "`/untrack <id>` — stop tracking\n"
        "`/chat <question>` — ask the AI agent\n"
        "`/alerts` — view your alerts\n"
        "`/help` — this message"
    )


@common_router.message(Command("help"))
async def cmd_help(message: Message, uow_factory, **kwargs) -> None:
    async with uow_factory() as uow:
        user = await _get_or_create_user(message, uow)
    plan_badge = "⭐ FREE" if user.plan == "free" else "💎 PAID"
    await message.answer(
        f"🐋 *WhaleDecode*\n\n"
        f"Plan: {plan_badge}\n\n"
        "Commands:\n"
        "`/wallets` — browse curated wallets\n"
        "`/track <id>` — track a wallet\n"
        "`/untrack <id>` — stop tracking\n"
        "`/chat <question>` — ask the AI agent\n"
        "`/alerts` — view your alerts\n"
        "`/help` — this message"
    )
