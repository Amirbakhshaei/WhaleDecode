from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.domain.entities.user import User

chat_router = Router(name="chat")


async def _get_or_create_user(message: Message, uow: UnitOfWork) -> User:
    tg_id = message.from_user.id
    existing = await uow.users.get_by_tg_id(tg_id)
    if existing:
        return existing
    user = User(tg_id=tg_id, username=message.from_user.username, plan="free")
    created = await uow.users.create(user)
    await uow.commit()
    return created


@chat_router.message(Command("chat"))
async def cmd_chat(message: Message, investigation_service, uow_factory, **kwargs) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: `/chat <your question>`\nExample: `/chat what did 0x742d... do recently?`")
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
        user = await _get_or_create_user(message, uow)
        alerts = await uow.alerts.list_by_user(user.id, limit=20)
    if not alerts:
        await message.answer("No alerts yet. Events are detected every 30 seconds.")
        return
    lines = ["*Your Recent Alerts:*\n"]
    for a in alerts:
        dedup = f" key: `{a.dedupe_key[:16]}...`" if a.dedupe_key else ""
        lines.append(f"• event `{a.event_id}` — {a.status} — {a.priority}{dedup}")
    await message.answer("\n".join(lines))
