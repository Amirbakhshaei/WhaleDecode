from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

chat_router = Router(name="chat")


@chat_router.message(Command("chat"))
async def cmd_chat(message: Message) -> None:
    await message.answer("AI chat coming soon — use the Gradio UI for now.")


@chat_router.message(Command("alerts"))
async def cmd_alerts(message: Message) -> None:
    await message.answer("Alerts not yet dispatched. Check back after Phase 7.")
