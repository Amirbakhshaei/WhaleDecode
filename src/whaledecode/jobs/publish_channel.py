import structlog
from aiogram import Bot

from whaledecode.adapters.db.session import async_sessionmaker
from whaledecode.adapters.telegram.formatters.relay import RelayFormatter
from whaledecode.config.settings import Settings

log = structlog.get_logger()


async def publish_channel(session_factory: async_sessionmaker, bot: Bot, settings: Settings) -> None:
    if not settings.CHANNEL_PUBLISH_ENABLED or not settings.CHANNEL_CHAT_ID:
        return

    from whaledecode.adapters.db.uow import UnitOfWork

    relay = RelayFormatter(settings)
    channel_id = settings.CHANNEL_CHAT_ID

    uow = UnitOfWork(session_factory)
    async with uow:
        events = await uow.candidate_events.list_unpublished(limit=settings.CHANNEL_MAX_DAILY)
        if not events:
            return

        published = 0
        for event in events:
            run = await uow.agent_runs.get_by_trigger("event", event.id)
            report = run.output_json if run else {}

            event_data = event.model_dump()
            msg = relay.format_channel_post(event_data, report)
            try:
                await bot.send_message(chat_id=channel_id, text=msg)
                await uow.candidate_events.mark_published(event.id)
                published += 1
                log.info("channel_published", event_id=event.id, event_type=event.event_type)
            except Exception as e:
                log.error("channel_publish_failed", event_id=event.id, error=str(e))
        await uow.commit()
    if published:
        log.info("channel_batch_done", count=published)
