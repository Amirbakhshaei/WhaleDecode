from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

admin_router = Router(name="admin")


@admin_router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    await message.answer("Admin panel coming soon.")


@admin_router.message(Command("admin_grant_paid"))
async def cmd_admin_grant_paid(message: Message) -> None:
    await message.answer("Grant not yet implemented.")
