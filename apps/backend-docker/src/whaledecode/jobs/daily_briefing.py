from datetime import UTC, datetime, timedelta

import structlog
from aiogram import Bot

from whaledecode.adapters.db.session import async_sessionmaker
from whaledecode.config.settings import Settings

log = structlog.get_logger()


async def run_daily_briefing(
    session_factory: async_sessionmaker, bot: Bot, settings: Settings
) -> None:
    """Generate and send Syndicate Intelligence Briefing to main channel.

    Aggregates top 3 highest-PnL syndicates detected over past 24h.
    """
    from sqlalchemy import select

    from whaledecode.adapters.db.models.syndicate_cluster import SyndicateClusterModel
    from whaledecode.adapters.db.uow import UnitOfWork

    uow = UnitOfWork(session_factory)
    async with uow:

        window_start = datetime.now(UTC) - timedelta(hours=24)
        clusters = await uow.session.execute(
            select(SyndicateClusterModel)
            .where(SyndicateClusterModel.window_end >= window_start)
            .order_by(SyndicateClusterModel.total_usd.desc())
            .limit(3)
        )
        top_clusters = list(clusters.scalars())

        if not top_clusters:
            log.info("briefing_no_syndicates")
            return

        # Build briefing message
        lines = [
            "🕵️ <b>WHALEDECODE | SYNDICATE INTELLIGENCE BRIEFING</b>",
            f"📅 {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"<b>Top {len(top_clusters)} Syndicates (24h):</b>",
            "",
        ]

        for i, cluster in enumerate(top_clusters, 1):
            token = getattr(cluster, "token_symbol", "UNKNOWN")
            chain = getattr(cluster, "chain", "").upper()
            total_usd = float(getattr(cluster, "total_usd", 0) or 0)
            wallet_count = int(getattr(cluster, "wallet_count", 0) or 0)
            cluster_type = getattr(cluster, "cluster_type", "UNKNOWN")
            root_label = getattr(cluster, "root_label", "") or "Unknown"

            lines.append(
                f"{i}. <b>{token}</b> ({chain}) — ${total_usd:,.0f}"
                f"\n   {wallet_count} wallets | {cluster_type}"
                f"\n   Funder: {root_label}"
            )

        lines.extend([
            "",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "<i>Not financial advice. DYOR. Data may be delayed.</i>",
        ])

        msg = "\n".join(lines)

        # Send to main channel if configured
        channel_id = settings.TELEGRAM_CHANNEL_ID or settings.CHANNEL_CHAT_ID
        if channel_id:
            try:
                await bot.send_message(chat_id=channel_id, text=msg, parse_mode="HTML")
                log.info("briefing_sent_to_channel", channel=channel_id)
            except Exception as e:
                log.error("briefing_channel_failed", error=str(e))

        # Also send to paid users
        users = await uow.users.list_by_plan("paid")
        sent = 0
        for user in users:
            if not user.alerts_enabled:
                continue
            try:
                await bot.send_message(chat_id=user.tg_id, text=msg, parse_mode="HTML")
                sent += 1
            except Exception as e:
                log.error("briefing_dispatch_failed", user_id=user.id, error=str(e))
        log.info("briefing_sent_to_users", users=sent, total=len(users))
