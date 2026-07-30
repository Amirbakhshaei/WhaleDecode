from html import escape

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from whaledecode.adapters.telegram.user_access import get_or_create_user
from whaledecode.config.tiers import get_limits

chat_router = Router(name="chat")


@chat_router.message(Command("ask"))
async def cmd_ask(message: Message, investigation_service, uow_factory, **kwargs) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: <code>/ask &lt;your question&gt;</code>\nExample: <code>/ask what did 0x742d... do recently?</code>")
        return

    async with uow_factory() as uow:
        user = await get_or_create_user(message.from_user.id, message.from_user.username, uow)
        limits = get_limits(user.plan)
        if user.daily_chat_count >= limits.chat_per_day:
            await message.answer(f"You've used {user.daily_chat_count}/{limits.chat_per_day} chats today. Upgrade for more.")
            return
        user.daily_chat_count += 1
        await uow.users.update(user)
        await uow.commit()

    question = args[1]
    await message.answer("🧠 Thinking...")
    try:
        response = await investigation_service.chat(question)
        await message.answer(response[:4000])
    except Exception as e:
        await message.answer(f"Sorry, I encountered an error: {escape(str(e)[:200])}")


@chat_router.message(Command("decode"))
async def cmd_decode(message: Message, investigation_service, uow_factory, **kwargs) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: <code>/decode &lt;tx_hash or address&gt;</code>\nExample: <code>/decode 0x1234...</code>")
        return

    async with uow_factory() as uow:
        user = await get_or_create_user(message.from_user.id, message.from_user.username, uow)
        limits = get_limits(user.plan)
        if user.daily_chat_count >= limits.chat_per_day:
            await message.answer(f"You've used {user.daily_chat_count}/{limits.chat_per_day} chats today. Upgrade for more.")
            return
        user.daily_chat_count += 1
        await uow.users.update(user)
        await uow.commit()

    target = args[1]
    await message.answer("🔍 Decoding...")
    try:
        response = await investigation_service.chat(f"Decode and analyze this address or transaction: {target}")
        await message.answer(response[:4000])
    except Exception as e:
        await message.answer(f"Sorry, I encountered an error: {escape(str(e)[:200])}")


@chat_router.message(Command("alerts"))
async def cmd_alerts(message: Message, uow_factory, **kwargs) -> None:
    async with uow_factory() as uow:
        user = await get_or_create_user(message.from_user.id, message.from_user.username, uow)
        parts = message.text.split()
        if len(parts) == 2:
            if parts[1].lower() in ("on", "enable", "yes"):
                user.alerts_enabled = True
                await uow.users.update(user)
                await uow.commit()
                await message.answer("✅ Alerts enabled.")
                return
            if parts[1].lower() in ("off", "disable", "no"):
                user.alerts_enabled = False
                await uow.users.update(user)
                await uow.commit()
                await message.answer("✅ Alerts disabled.")
                return

        alerts = await uow.alerts.list_by_user(user.id, limit=20)
    status = "enabled" if user.alerts_enabled else "disabled"
    lines = [f"<b>Your Alerts ({status}):</b>\n"]
    if not alerts:
        lines.append("No alerts yet. Events are detected every 30 seconds.")
    else:
        for a in alerts:
            dedup = f" key: <code>{a.dedupe_key[:16]}...</code>" if a.dedupe_key else ""
            lines.append(f"• event <code>{a.event_id}</code> — {a.status} — {a.priority}{dedup}")
    await message.answer("\n".join(lines))


@chat_router.message(Command("briefing"))
async def cmd_briefing(message: Message, investigation_service, uow_factory, **kwargs) -> None:
    async with uow_factory() as uow:
        user = await get_or_create_user(message.from_user.id, message.from_user.username, uow)
        limits = get_limits(user.plan)
        if not limits.briefing_on_demand and user.daily_chat_count >= limits.chat_per_day:
            await message.answer("Briefing is available at 08:00 UTC for free users. Upgrade for on-demand access.")
            return
    await message.answer("📋 Generating briefing...")
    try:
        briefing = await investigation_service.generate_briefing(user.id)
        await message.answer(briefing[:4000])
    except Exception as e:
        await message.answer(f"Sorry, I encountered an error: {escape(str(e)[:200])}")
