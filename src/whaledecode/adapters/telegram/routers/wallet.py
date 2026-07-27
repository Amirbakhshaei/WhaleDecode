from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.domain.entities.user import User

wallet_router = Router(name="wallet")


async def _get_or_create_user(message: Message, uow: UnitOfWork) -> User:
    tg_id = message.from_user.id
    existing = await uow.users.get_by_tg_id(tg_id)
    if existing:
        return existing
    user = User(tg_id=tg_id, username=message.from_user.username, plan="free")
    created = await uow.users.create(user)
    await uow.commit()
    return created


@wallet_router.message(Command("wallets"))
async def cmd_wallets(message: Message, uow_factory, **kwargs) -> None:
    async with uow_factory() as uow:
        wallets = await uow.curated_wallets.list_active()
    if not wallets:
        await message.answer("No curated wallets available yet.")
        return
    lines = ["*Curated Wallets:*\n"]
    for w in wallets:
        addr_short = f"{w.address[:6]}...{w.address[-4:]}"
        lines.append(f"`{w.id}` | {addr_short} | {w.chain.value} | {w.label} | score: {w.quality_score}")
    await message.answer("\n".join(lines))


@wallet_router.message(Command("track"))
async def cmd_track(message: Message, uow_factory, wallet_service, **kwargs) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: `/track <wallet_id>`")
        return
    wallet_id_str = args[1].strip()
    if not wallet_id_str.isdigit():
        await message.answer("Usage: `/track <wallet_id>` — wallet_id must be a number.")
        return
    wallet_id = int(wallet_id_str)
    async with uow_factory() as uow:
        user = await _get_or_create_user(message, uow)
        curated = await uow.curated_wallets.get(wallet_id)
        if curated is None:
            await message.answer(f"Wallet `{wallet_id}` not found in curated list.")
            return
        await wallet_service.track(user.id, wallet_id, curated.chain.value)
    await message.answer(f"✅ Now tracking `{curated.label}` ({curated.address[:6]}...{curated.address[-4:]})")


@wallet_router.message(Command("untrack"))
async def cmd_untrack(message: Message, wallet_service, uow_factory, **kwargs) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: `/untrack <wallet_id>`")
        return
    wallet_id_str = args[1].strip()
    if not wallet_id_str.isdigit():
        await message.answer("Usage: `/untrack <wallet_id>` — wallet_id must be a number.")
        return
    wallet_id = int(wallet_id_str)
    async with uow_factory() as uow:
        user = await _get_or_create_user(message, uow)
    await wallet_service.untrack(user.id, wallet_id)
    await message.answer(f"✅ Stopped tracking wallet `{wallet_id}`")
