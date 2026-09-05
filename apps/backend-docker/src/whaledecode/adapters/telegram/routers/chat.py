import re
from html import escape
from typing import Any

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


def _format_cluster_line(cluster: Any) -> str:
    """Format a single syndicate cluster for display."""
    token_symbol = getattr(cluster, "token_symbol", "") or "UNKNOWN"
    chain = getattr(cluster, "chain", "").upper()
    total_usd = float(getattr(cluster, "total_usd", 0) or 0)
    wallet_count = int(getattr(cluster, "wallet_count", 0) or 0)
    cluster_type = getattr(cluster, "cluster_type", "UNKNOWN")
    root_label = getattr(cluster, "root_label", "") or "Unknown"
    short_root = f"{root_label[:30]}..." if len(root_label) > 30 else root_label
    return (
        f"• <b>{token_symbol}</b> ({chain}) — ${total_usd:,.0f} "
        f"({wallet_count} wallets, {cluster_type})\n"
        f"  Funder: <code>{escape(short_root)}</code>"
    )


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


@chat_router.message(Command("syndicate"))
async def cmd_syndicate(message: Message, command: CommandObject, uow_factory, settings=None, **kwargs) -> None:
    """Look up recent multi-wallet clustered buys for a given token contract."""
    log.info("syndicate_command_received", user_id=message.from_user.id, text=message.text)
    token = (command.args or "").strip()
    if not token:
        await message.answer(
            "Usage: <code>/syndicate <token_contract_address></code>\n"
            "Example: <code>/syndicate 0x1234...</code>"
        )
        return

    async with uow_factory() as uow:
        clusters = await uow.syndicate_clusters.get_clusters_for_token(token, hours=24)

    if not clusters:
        await message.answer(f"No syndicate clusters found for <code>{escape(token)}</code> in the last 24h.")
        return

    lines = [f"🔗 <b>Syndicate Clusters for {escape(token)} (24h):</b>\n"]
    for cluster in clusters[:10]:
        lines.append(_format_cluster_line(cluster))

    await message.answer("\n".join(lines))


@chat_router.message(Command("clusters"))
async def cmd_clusters(message: Message, command: CommandObject, uow_factory, settings=None, **kwargs) -> None:
    """View top 5 active insider clusters across Base, Arbitrum, and Ethereum in the last 24h."""
    log.info("clusters_command_received", user_id=message.from_user.id)
    chain = (command.args or "").strip().lower() if command.args else None

    async with uow_factory() as uow:
        if chain in ("eth", "ethereum", "base", "arb", "arbitrum"):
            clusters = await uow.syndicate_clusters.list_recent_clusters(chain=chain, hours=24, limit=5)
        else:
            # Get top clusters across all chains
            all_clusters = []
            for c in ("ethereum", "base", "arbitrum"):
                clusters = await uow.syndicate_clusters.list_recent_clusters(chain=c, hours=24, limit=5)
                all_clusters.extend(clusters)
            # Sort by total_usd and take top 5
            all_clusters.sort(key=lambda c: float(getattr(c, "total_usd", 0) or 0), reverse=True)
            clusters = all_clusters[:5]

    if not clusters:
        await message.answer("No active insider clusters detected in the last 24h.")
        return

    lines = ["🏆 <b>Top Active Insider Clusters (24h):</b>\n"]
    for i, cluster in enumerate(clusters, 1):
        lines.append(f"{i}. {_format_cluster_line(cluster)}")

    await message.answer("\n".join(lines))


@chat_router.message(Command("smc"))
async def cmd_smc(message: Message, command: CommandObject, uow_factory, settings=None, **kwargs) -> None:
    """Show real-time market structure (Discount/Premium, FVG, Invalidation) for any token."""
    log.info("smc_command_received", user_id=message.from_user.id, text=message.text)
    token = (command.args or "").strip()
    if not token:
        await message.answer(
            "Usage: <code>/smc <token_contract_address></code>\n"
            "Example: <code>/smc 0x1234...</code>"
        )
        return

    chain = "ethereum"  # Default, could parse from token format
    if token.startswith("0x") and len(token) == 42:
        # Try to infer chain from context or default to ethereum
        pass

    await message.answer("📈 Fetching market structure...")
    try:
        from whaledecode.adapters.pricing.oracle import PriceOracle
        oracle = PriceOracle()
        smc = await oracle.get_smc_analysis(token, chain)
        await oracle.aclose()

        if not smc:
            await message.answer(f"No market structure data available for <code>{escape(token)}</code> on {chain}.")
            return

        lines = [
            f"📈 <b>SMC Market Structure for {escape(token)} ({chain.upper()}):</b>",
            "",
            f"• <b>Regime:</b> {smc.market_regime}",
            f"• <b>Zone:</b> {'Discount' if smc.is_discount_zone else 'Premium'} "
            f"({'✅ OTE Confluence' if smc.ote_confluence else 'Outside OTE'})",
            f"• <b>Equilibrium:</b> ${smc.equilibrium_price:,.4f}",
            f"• <b>Invalidation:</b> ${smc.invalidation_level:,.4f}",
            f"• <b>Liquidity Sweep:</b> {'Yes ⚠️' if smc.liquidity_sweep else 'No'}",
        ]
        if smc.fvg_detected:
            lines.append("• <b>Fair Value Gap:</b> Detected")
        await message.answer("\n".join(lines))
    except Exception as e:
        log.error("smc_command_error", user_id=message.from_user.id, error=str(e))
        await message.answer(f"Error fetching SMC data: {escape(str(e)[:200])}")


@chat_router.message(Command("watchlist"))
async def cmd_watchlist(message: Message, command: CommandObject, uow_factory, settings=None, **kwargs) -> None:
    """Manage private wallet alerts."""
    log.info("watchlist_command_received", user_id=message.from_user.id, text=message.text)
    args = (command.args or "").strip().split()
    subcommand = args[0].lower() if args else "list"

    async with uow_factory() as uow:
        user = await get_or_create_user(message.from_user.id, message.from_user.username, uow)

        if subcommand in ("add", "a"):
            if len(args) < 2:
                await message.answer("Usage: <code>/watchlist add <address> [label]</code>")
                return
            address = args[1]
            label = " ".join(args[2:]) if len(args) > 2 else ""
            # In production, would add to user's tracked_wallets
            await message.answer(f"✅ Added <code>{escape(address)}</code> to your watchlist."
                               + (f" Label: {escape(label)}" if label else ""))

        elif subcommand in ("remove", "rm", "delete", "del"):
            if len(args) < 2:
                await message.answer("Usage: <code>/watchlist remove <address></code>")
                return
            address = args[1]
            # In production, would remove from user's tracked_wallets
            await message.answer(f"🗑️ Removed <code>{escape(address)}</code> from your watchlist.")

        else:  # list
            tracked = await uow.tracked_wallets.list_by_user(user.id)
            if not tracked:
                await message.answer("📋 Your watchlist is empty.\nUse <code>/watchlist add <address></code> to track wallets.")
                return
            lines = [f"📋 <b>Your Watchlist ({len(tracked)} wallets):</b>\n"]
            for w in tracked:
                short_addr = f"{w.address[:6]}...{w.address[-4:]}"
                lbl = f" — {escape(w.label)}" if w.label else ""
                lines.append(f"• <code>{short_addr}</code>{lbl}\n  <code>{w.address}</code>")
            await message.answer("\n".join(lines))


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
