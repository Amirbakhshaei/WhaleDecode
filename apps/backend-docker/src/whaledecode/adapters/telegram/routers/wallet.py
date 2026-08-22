from html import escape

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from whaledecode.adapters.telegram.user_access import get_or_create_user

wallet_router = Router(name="wallet")


@wallet_router.message(Command("wallets"))
async def cmd_wallets(message: Message, uow_factory, **kwargs) -> None:
    async with uow_factory() as uow:
        wallets = await uow.curated_wallets.list_active()
    if not wallets:
        await message.answer("No curated wallets available yet.")
        return
    lines = ["<b>Curated Wallets:</b>\n"]
    for w in wallets:
        addr_short = f"{w.address[:6]}...{w.address[-4:]}"
        lines.append(f"<code>{w.id}</code> | {addr_short} | {w.chain.name} | {w.label} | score: {w.quality_score}")
    await message.answer("\n".join(lines))


@wallet_router.message(Command("track"))
async def cmd_track(message: Message, command: CommandObject, uow_factory, wallet_service, **kwargs) -> None:
    wallet_id_str = (command.args or "").strip()
    if not wallet_id_str.isdigit():
        await message.answer("Usage: <code>/track &lt;wallet_id&gt;</code> — wallet_id must be a number.")
        return
    wallet_id = int(wallet_id_str)
    async with uow_factory() as uow:
        user = await get_or_create_user(message.from_user.id, message.from_user.username, uow)
        curated = await uow.curated_wallets.get(wallet_id)
        if curated is None:
            await message.answer(f"Wallet <code>{wallet_id}</code> not found in curated list.")
            return
        await wallet_service.track(user.id, wallet_id, curated.chain.name)
    await message.answer(f"✅ Now tracking <code>{escape(curated.label)}</code> ({curated.address[:6]}...{curated.address[-4:]})")


@wallet_router.message(Command("untrack"))
async def cmd_untrack(message: Message, command: CommandObject, wallet_service, uow_factory, **kwargs) -> None:
    wallet_id_str = (command.args or "").strip()
    if not wallet_id_str.isdigit():
        await message.answer("Usage: <code>/untrack &lt;wallet_id&gt;</code> — wallet_id must be a number.")
        return
    wallet_id = int(wallet_id_str)
    async with uow_factory() as uow:
        user = await get_or_create_user(message.from_user.id, message.from_user.username, uow)
    await wallet_service.untrack(user.id, wallet_id)
    await message.answer(f"✅ Stopped tracking wallet <code>{wallet_id}</code>")
