import asyncio
import signal

import structlog
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from whaledecode.adapters.db.session import create_session_factory
from whaledecode.config.settings import Settings

log = structlog.get_logger()


async def run_worker(settings: Settings) -> None:
    session_factory = create_session_factory(settings)
    bot = Bot(
        token=settings.BOT_TOKEN.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        _reset_daily_counters,
        trigger="cron",
        hour=0,
        minute=0,
        args=[session_factory],
        id="reset_daily_counters",
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _run_briefing,
        trigger="cron",
        hour=8,
        minute=0,
        args=[session_factory, bot, settings],
        id="daily_briefing",
        misfire_grace_time=600,
    )

    log.info("worker_started")

    stop_event = asyncio.Event()

    def shutdown(sig: int) -> None:
        log.info("worker_shutdown_signal", signal=sig)
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: shutdown(s))
        except NotImplementedError:
            pass

    scheduler.start()

    poll_task = asyncio.create_task(_poll_loop(session_factory, settings))
    alert_task = asyncio.create_task(_alert_loop(session_factory, bot, settings))
    channel_task = asyncio.create_task(_channel_loop(session_factory, bot, settings))

    await stop_event.wait()

    poll_task.cancel()
    alert_task.cancel()
    channel_task.cancel()
    scheduler.shutdown(wait=False)
    await bot.session.close()
    log.info("worker_stopped")


async def _poll_loop(session_factory, settings: Settings) -> None:
    from whaledecode.jobs.poll_wallets import poll_wallets

    while True:
        try:
            await poll_wallets(session_factory, settings)
        except Exception as e:
            log.error("poll_loop_error", error=str(e))
        await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)


async def _alert_loop(session_factory, bot: Bot, settings: Settings) -> None:
    from whaledecode.jobs.send_alerts import send_alerts

    interval = settings.PAID_ALERT_BATCH_INTERVAL_SECONDS
    while True:
        try:
            await send_alerts(session_factory, bot, settings)
        except Exception as e:
            log.error("alert_loop_error", error=str(e))
        await asyncio.sleep(interval)


async def _channel_loop(session_factory, bot: Bot, settings: Settings) -> None:
    from whaledecode.jobs.publish_channel import publish_channel

    while True:
        try:
            await publish_channel(session_factory, bot, settings)
        except Exception as e:
            log.error("channel_loop_error", error=str(e))
        await asyncio.sleep(60)


async def _run_briefing(session_factory, bot: Bot, settings: Settings) -> None:
    from whaledecode.jobs.daily_briefing import run_daily_briefing
    await run_daily_briefing(session_factory, bot, settings)


async def _reset_daily_counters(session_factory) -> None:
    from sqlalchemy import update

    from whaledecode.adapters.db.models.user import UserModel

    async with session_factory() as session:
        stmt = update(UserModel).values(daily_chat_count=0, daily_alert_count=0)
        await session.execute(stmt)
        await session.commit()
    log.info("daily_counters_reset")
