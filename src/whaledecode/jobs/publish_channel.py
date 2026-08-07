import structlog
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import LinkPreviewOptions

from whaledecode.adapters.db.session import async_sessionmaker
from whaledecode.adapters.telegram.formatters.channel_formatter import (
    format_channel_post_markdown,
)
from whaledecode.adapters.telegram.keyboards import build_keyboard
from whaledecode.config.settings import Settings

log = structlog.get_logger()


async def publish_channel(session_factory: async_sessionmaker, bot: Bot, settings: Settings) -> None:
    channel_id = settings.TELEGRAM_CHANNEL_ID or settings.CHANNEL_CHAT_ID
    if not settings.CHANNEL_PUBLISH_ENABLED or not channel_id:
        return

    from whaledecode.adapters.db.uow import UnitOfWork

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
            msg = format_channel_post_markdown(event_data, report)
            tx_hash = event_data.get("tx_hash", "")
            keyboard = build_keyboard(tx_hash)
            try:
                await bot.send_message(
                    chat_id=channel_id,
                    text=msg,
                    parse_mode=ParseMode.MARKDOWN_V2,
                    reply_markup=keyboard,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
                await uow.candidate_events.mark_published(event.id)
                published += 1
                log.info("channel_published", event_id=event.id, event_type=event.event_type)
            except Exception as e:
                log.warning(
                    "channel_publish_markdown_failed",
                    event_id=event.id,
                    error=str(e),
                )
                try:
                    await bot.send_message(
                        chat_id=channel_id,
                        text=str(report.get("summary", "")),
                        reply_markup=keyboard,
                    )
                    await uow.candidate_events.mark_published(event.id)
                    published += 1
                    log.info("channel_published_plaintext", event_id=event.id)
                except Exception as e2:
                    log.error("channel_publish_failed", event_id=event.id, error=str(e2))
        await uow.commit()
    if published:
        log.info("channel_batch_done", count=published)
