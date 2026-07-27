from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

admin_router = Router(name="admin")


@admin_router.message(Command("admin"))
async def cmd_admin(message: Message, uow_factory, settings, **kwargs) -> None:
    tg_id = message.from_user.id
    if tg_id not in settings.ADMIN_USER_IDS:
        await message.answer("Access denied.")
        return
    async with uow_factory() as uow:
        users = await uow.users.list_by_plan("free")
        paid = await uow.users.list_by_plan("paid")
    await message.answer(
        f"<b>Admin Panel</b>\n\n"
        f"Users: {len(users) + len(paid)}\n"
        f"  Free: {len(users)}\n"
        f"  Paid: {len(paid)}\n\n"
        f"Commands:\n"
        f"<code>/admin_grant_paid &lt;tg_id&gt;</code> — grant paid plan"
    )


@admin_router.message(Command("admin_grant_paid"))
async def cmd_admin_grant_paid(message: Message, uow_factory, settings, **kwargs) -> None:
    tg_id = message.from_user.id
    if tg_id not in settings.ADMIN_USER_IDS:
        await message.answer("Access denied.")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: <code>/admin_grant_paid &lt;tg_id&gt;</code>")
        return
    target_tg_id = int(args[1].strip())
    async with uow_factory() as uow:
        user = await uow.users.get_by_tg_id(target_tg_id)
        if user is None:
            await message.answer(f"User <code>{target_tg_id}</code> not found.")
            return
        user.plan = "paid"
        await uow.users.update(user)
        await uow.commit()
    await message.answer(f"✅ Granted PAID plan to user <code>{target_tg_id}</code>")
