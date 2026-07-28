from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from whaledecode.adapters.telegram.user_access import get_or_create_user

chat_router = Router(name="chat")


@chat_router.message(Command("chat"))
async def cmd_chat(message: Message, investigation_service, uow_factory, **kwargs) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: <code>/chat &lt;your question&gt;</code>\nExample: <code>/chat what did 0x742d... do recently?</code>")
        return
    question = args[1]
    await message.answer("🧠 Thinking...")
    try:
        response = await investigation_service.chat(question)
        await message.answer(response[:4000])
    except Exception as e:
        await message.answer(f"Sorry, I encountered an error: {str(e)[:200]}")


@chat_router.message(Command("alerts"))
async def cmd_alerts(message: Message, uow_factory, **kwargs) -> None:
    async with uow_factory() as uow:
        user = await get_or_create_user(message.from_user.id, message.from_user.username, uow)
        alerts = await uow.alerts.list_by_user(user.id, limit=20)
    if not alerts:
        await message.answer("No alerts yet. Events are detected every 30 seconds.")
        return
    lines = ["<b>Your Recent Alerts:</b>\n"]
    for a in alerts:
        dedup = f" key: <code>{a.dedupe_key[:16]}...</code>" if a.dedupe_key else ""
        lines.append(f"• event <code>{a.event_id}</code> — {a.status} — {a.priority}{dedup}")
    await message.answer("\n".join(lines))
