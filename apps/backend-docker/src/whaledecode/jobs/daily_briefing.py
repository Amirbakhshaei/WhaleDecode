import structlog
from aiogram import Bot

from whaledecode.adapters.db.session import async_sessionmaker
from whaledecode.config.settings import Settings

log = structlog.get_logger()


async def run_daily_briefing(
    session_factory: async_sessionmaker, bot: Bot, settings: Settings
) -> None:
    from whaledecode.adapters.db.uow import UnitOfWork
    from whaledecode.adapters.llm.factory import LLMFactory
    from whaledecode.adapters.llm_graph.reasoner import LangGraphReasoner
    from whaledecode.adapters.telegram.formatters.relay import RelayFormatter

    llm_factory = LLMFactory(settings)
    reasoner = LangGraphReasoner(settings, llm_factory)
    relay = RelayFormatter(settings)

    uow = UnitOfWork(session_factory)
    async with uow:
        users = await uow.users.list_by_plan("paid")
        if not users:
            log.info("briefing_no_paid_users")
            return

        events = await uow.candidate_events.list_by_status("NEW", limit=50)

        briefing_input = {
            "events": [
                {
                    "score": e.score,
                    "address": str(e.tx_hash),
                    "chain": e.chain,
                    "event_type": e.event_type,
                    "label": e.event_type,
                }
                for e in events
            ],
        }

        result = await reasoner.generate_briefing(briefing_input)
        msg = relay.format_briefing(result)

        sent = 0
        for user in users:
            if not user.alerts_enabled:
                continue
            try:
                await bot.send_message(chat_id=user.tg_id, text=msg[:4000])
                sent += 1
            except Exception as e:
                log.error("briefing_dispatch_failed", user_id=user.id, error=str(e))
        log.info("briefing_sent", users=sent, total=len(users))
