import re
from html import escape

import structlog
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from whaledecode.adapters.telegram.user_access import get_or_create_user
from whaledecode.application.services.user_service import (
    UPGRADE_CTA_MESSAGE,
    check_and_decrement_quota,
)
from whaledecode.config.tiers import get_limits
from whaledecode.domain.exceptions import QuotaExceededError
from whaledecode.domain.value_objects.address import EVMAddress

log = structlog.get_logger()

chat_router = Router(name="chat")

_GREETINGS = {"hi", "hello", "hey", "help"}

TX_HASH_REGEX = re.compile(r"^0x[a-fA-F0-9]{64}$")


def is_evm_address(value: str) -> bool:
    try:
        EVMAddress(value)
        return True
    except ValueError:
        return False

def is_greeting(query: str) -> bool:
    q = query.strip().lower()
    return len(q) < 10 or q in _GREETINGS


async def _spend_quota(message: Message, uow_factory, settings=None) -> bool:
    """Spend one free-tier query. False when quota is exhausted (CTA sent).

    Admin Telegram IDs are exempt so operators are never blocked.
    """
    if settings and message.from_user.id in settings.ADMIN_USER_IDS:
        return True
    async with uow_factory() as uow:
        try:
            await check_and_decrement_quota(uow, message.from_user.id, admin_ids=settings.ADMIN_USER_IDS if settings else None)
            await uow.commit()
            return True
        except QuotaExceededError:
            await message.answer(UPGRADE_CTA_MESSAGE)
            return False


async def _search_curated_entities(uow_factory, query: str) -> str | None:
    """Find curated wallets by label/category; None when nothing matches.

    Pure DB lookup (no LLM cost) — invalid inputs short-circuit here instead of
    ever reaching the on-chain tools.
    """
    async with uow_factory() as uow:
        matches = await uow.curated_wallets.search_by_label_or_category(query, limit=5)
    if not matches:
        return None
    lines = [f"🔎 <b>Found {len(matches)} entities matching '{escape(query)}':</b>\n"]
    for w in matches:
        short_addr = f"{w.address[:6]}...{w.address[-4:]}"
        label = escape(w.label or "Unlabeled")
        lines.append(
            f"• <b>{label}</b> ({w.chain.name}) — {short_addr}\n"
            f"  <code>{w.address}</code>\n"
            f"  👉 /ask {w.address}\n"
        )
    return "\n".join(lines)


@chat_router.message(Command("ask"))
async def cmd_ask(message: Message, command: CommandObject, investigation_service, uow_factory, settings=None, **kwargs) -> None:
    log.info("ask_command_received", user_id=message.from_user.id, text=message.text)
    question = (command.args or "").strip()
    if not question:
        await message.answer("Usage: <code>/ask &lt;your question&gt;</code>\nExample: <code>/ask 0x742d...</code>")
        return

    async with uow_factory() as uow:
        user = await get_or_create_user(message.from_user.id, message.from_user.username, uow)
        limits = get_limits(user.plan)
        is_admin = bool(settings and message.from_user.id in settings.ADMIN_USER_IDS)
        if not is_admin and user.daily_chat_count >= limits.chat_per_day:
            await message.answer(f"You've used {user.daily_chat_count}/{limits.chat_per_day} chats today. Upgrade for more.")
            return
        if not is_admin:
            user.daily_chat_count += 1
            await uow.users.update(user)
        await uow.commit()

    # Deterministic triage: tx hash → tx investigation, wallet address → wallet
    # investigation, otherwise search the curated-entity DB before any LLM call.
    if TX_HASH_REGEX.match(question):
        prompt = f"Decode and analyze this on-chain transaction: {question}"
    elif is_evm_address(question):
        prompt = f"Investigate this wallet: {question}"
    else:
        entity_hits = await _search_curated_entities(uow_factory, question)
        if entity_hits is not None:
            await message.answer(entity_hits)
            return
        if is_greeting(question):
            await message.answer(
                "👋 Hey! I'm WhaleDecode — your on-chain intelligence bot.\n\n"
                "Send me a wallet address, transaction hash, or token symbol to investigate!\n\n"
                "Examples:\n"
                "• <code>/ask 0x742d...</code>\n"
                "• <code>/ask binance</code>\n"
                "• <code>/decode 0x1234...</code>"
            )
            return
        prompt = question

    if not await _spend_quota(message, uow_factory, settings):
        return

    await message.answer("🧠 Thinking...")
    try:
        result = await investigation_service.chat(prompt, thread_id=str(message.from_user.id), model="ask")
        await message.answer(result[:4000])
    except ConnectionError as e:
        log.error("ask_connection_error", user_id=message.from_user.id, error=str(e))
        await message.answer("LLM connection failed — check GROQ_API_KEY or try again shortly.")
    except Exception as e:
        log.error("ask_error", user_id=message.from_user.id, error=str(e))
        await message.answer(f"Sorry, I encountered an error: {escape(str(e)[:200])}")


@chat_router.message(Command("decode"))
async def cmd_decode(message: Message, command: CommandObject, investigation_service, uow_factory, settings=None, **kwargs) -> None:
    log.info("decode_command_received", user_id=message.from_user.id, text=message.text)
    target = (command.args or "").strip()
    if not target:
        await message.answer("Usage: <code>/decode &lt;tx_hash or address&gt;</code>\nExample: <code>/decode 0x1234...</code>")
        return

    async with uow_factory() as uow:
        user = await get_or_create_user(message.from_user.id, message.from_user.username, uow)
        limits = get_limits(user.plan)
        is_admin = bool(settings and message.from_user.id in settings.ADMIN_USER_IDS)
        if not is_admin and user.daily_chat_count >= limits.chat_per_day:
            await message.answer(f"You've used {user.daily_chat_count}/{limits.chat_per_day} chats today. Upgrade for more.")
            return
        if not is_admin:
            user.daily_chat_count += 1
            await uow.users.update(user)
        await uow.commit()

    if not await _spend_quota(message, uow_factory, settings):
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
async def cmd_alerts(message: Message, command: CommandObject, uow_factory, **kwargs) -> None:
    async with uow_factory() as uow:
        user = await get_or_create_user(message.from_user.id, message.from_user.username, uow)
        setting = (command.args or "").strip().lower()
        if setting:
            if setting in ("on", "enable", "yes"):
                user.alerts_enabled = True
                await uow.users.update(user)
                await uow.commit()
                await message.answer("✅ Alerts enabled.")
                return
            if setting in ("off", "disable", "no"):
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
async def cmd_briefing(message: Message, investigation_service, uow_factory, settings=None, **kwargs) -> None:
    async with uow_factory() as uow:
        user = await get_or_create_user(message.from_user.id, message.from_user.username, uow)
        limits = get_limits(user.plan)
        is_admin = bool(settings and message.from_user.id in settings.ADMIN_USER_IDS)
        if not is_admin and not limits.briefing_on_demand and user.daily_chat_count >= limits.chat_per_day:
            await message.answer("Briefing is available at 08:00 UTC for free users. Upgrade for on-demand access.")
            return
    await message.answer("📋 Generating briefing...")
    try:
        briefing = await investigation_service.generate_briefing(user.id)
        await message.answer(briefing[:4000])
    except Exception as e:
        await message.answer(f"Sorry, I encountered an error: {escape(str(e)[:200])}")


@chat_router.message()
async def cmd_chat_text(message: Message, investigation_service, uow_factory, settings=None, **kwargs) -> None:
    """Catch-all free-text handler: route any non-command message to the chat agent.

    Powers the Intelligence Hub "Ask AI" flow — after clicking a button the user
    types a follow-up and it is answered here.
    """
    question = (message.text or "").strip()
    if not question:
        return

    async with uow_factory() as uow:
        user = await get_or_create_user(message.from_user.id, message.from_user.username, uow)
        limits = get_limits(user.plan)
        is_admin = bool(settings and message.from_user.id in settings.ADMIN_USER_IDS)
        if not is_admin and user.daily_chat_count >= limits.chat_per_day:
            await message.answer(f"You've used {user.daily_chat_count}/{limits.chat_per_day} chats today. Upgrade for more.")
            return
        if not is_admin:
            user.daily_chat_count += 1
            await uow.users.update(user)
        await uow.commit()

    if is_greeting(question):
        await message.answer(
            "👋 Hey! I'm WhaleDecode — your on-chain intelligence bot.\n\n"
            "Send me a wallet address, transaction hash, or token symbol to investigate!\n\n"
            "Examples:\n"
            "• <code>/ask 0x742d...</code>\n"
            "• <code>/ask binance</code>\n"
            "• <code>/decode 0x1234...</code>"
        )
        return

    if not await _spend_quota(message, uow_factory, settings):
        return

    await message.answer("🧠 Thinking...")
    try:
        result = await investigation_service.chat(question, thread_id=str(message.from_user.id))
        await message.answer(result[:4000])
    except ConnectionError as e:
        log.error("chat_text_connection_error", user_id=message.from_user.id, error=str(e))
        await message.answer("LLM connection failed — check GROQ_API_KEY or try again shortly.")
    except Exception as e:
        log.error("chat_text_error", user_id=message.from_user.id, error=str(e))
        await message.answer(f"Sorry, I encountered an error: {escape(str(e)[:200])}")
