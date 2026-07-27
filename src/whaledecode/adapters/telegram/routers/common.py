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
        user = await _get_or_create_user(message, uow)
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
