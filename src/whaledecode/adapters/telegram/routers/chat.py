from html import escape

import structlog
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from whaledecode.adapters.telegram.user_access import get_or_create_user
from whaledecode.application.services.user_service import (
    UPGRADE_CTA_MESSAGE,
    check_and_decrement_quota,
)
from whaledecode.config.tiers import get_limits
from whaledecode.domain.exceptions import QuotaExceededError

log = structlog.get_logger()

chat_router = Router(name="chat")

_GREETINGS = {"hi", "hello", "hey", "help"}


def is_greeting(query: str) -> bool:
    q = query.strip().lower()
    return len(q) < 10 or q in _GREETINGS


async def _spend_quota(message: Message, uow_factory) -> bool:
    """Spend one free-tier query. False when quota is exhausted (CTA sent)."""
    async with uow_factory() as uow:
        try:
            await check_and_decrement_quota(uow, message.from_user.id)
            await uow.commit()
            return True
        except QuotaExceededError:
            await message.answer(UPGRADE_CTA_MESSAGE)
            return False


@chat_router.message(Command("ask"))
async def cmd_ask(message: Message, investigation_service, uow_factory, **kwargs) -> None:
    log.info("ask_command_received", user_id=message.from_user.id, text=message.text)
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

    if is_greeting(question):
        await message.answer(
            "👋 Hey! I'm WhaleDecode — your on-chain intelligence bot.\n\n"
            "Send me a wallet address, transaction hash, or token symbol to investigate!\n\n"
            "Examples:\n"
            "• <code>/ask what did 0x742d... do recently?</code>\n"
            "• <code>/decode 0x1234...</code>"
        )
        return

    if not await _spend_quota(message, uow_factory):
        return

    await message.answer("🧠 Thinking...")
    try:
        result = await investigation_service.chat(question, thread_id=str(message.from_user.id))
        await message.answer(result[:4000])
    except ConnectionError as e:
        log.error("ask_connection_error", user_id=message.from_user.id, error=str(e))
        await message.answer("LLM connection failed — check GROQ_API_KEY or try again shortly.")
    except Exception as e:
        log.error("ask_error", user_id=message.from_user.id, error=str(e))
        await message.answer(f"Sorry, I encountered an error: {escape(str(e)[:200])}")


@chat_router.message(Command("decode"))
async def cmd_decode(message: Message, investigation_service, uow_factory, **kwargs) -> None:
    log.info("decode_command_received", user_id=message.from_user.id, text=message.text)
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
    if not await _spend_quota(message, uow_factory):
        return
    await message.answer("🔍 Decoding...")
    try:
        response = await investigation_service.chat(
            f"Decode and analyze this address or transaction: {target}",
            thread_id=str(message.from_user.id),
        )
        await message.answer(response[:4000])
    except ConnectionError as e:
        log.error("decode_connection_error", user_id=message.from_user.id, error=str(e))
        await message.answer("LLM connection failed — check GROQ_API_KEY or try again shortly.")
    except Exception as e:
        log.error("decode_error", user_id=message.from_user.id, error=str(e))
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
