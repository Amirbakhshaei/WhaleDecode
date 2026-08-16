import asyncio
import signal

import structlog
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from whaledecode.adapters.db.session import create_session_factory
from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.adapters.llm.factory import LLMFactory
from whaledecode.adapters.llm_graph.reasoner import LangGraphReasoner
from whaledecode.application.fetcher import LiveBlockchainFetcher
from whaledecode.application.services.investigation import InvestigationService
from whaledecode.application.worker import BackgroundAIWorker
from whaledecode.config.settings import Settings
from whaledecode.infrastructure.telemetry import capture_exception, init_sentry

log = structlog.get_logger()


async def run_worker(settings: Settings) -> None:
    init_sentry(settings)
    session_factory = create_session_factory(settings)
    bot = Bot(
        token=settings.BOT_TOKEN.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    llm_factory = LLMFactory(settings)
    reasoner = LangGraphReasoner(settings, llm_factory)

    def _uow() -> UnitOfWork:
        return UnitOfWork(session_factory)

    investigation_service = InvestigationService(_uow, reasoner, settings)

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

    # Start fetcher (polling) and supervisor tasks
    fetcher = LiveBlockchainFetcher(session_factory, settings)
    fetcher_task = asyncio.create_task(fetcher.run(stop_event))

    supervisor_tasks = launch_supervisor_tasks(
        session_factory, investigation_service, settings, bot, stop_event
    )

    try:
        await stop_event.wait()
    finally:
        fetcher_task.cancel()
        for t in supervisor_tasks:
            t.cancel()
        await asyncio.gather(fetcher_task, *supervisor_tasks, return_exceptions=True)
        await reasoner.close()
        await bot.session.close()
        log.info("worker_stopped")


def launch_supervisor_tasks(
    session_factory,
    investigation_service,
    settings: Settings,
    bot: Bot,
    stop_event: asyncio.Event,
) -> list[asyncio.Task]:
    """Start the consumer supervisor tasks (worker + alert loop + cron jobs).
    Returns list of tasks to be awaited/cancelled by caller.
    """
    # Scheduler for cron jobs (daily briefing, counter reset)
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
    scheduler.add_job(
        _purge_stale_events,
        trigger="cron",
        hour=3,
        minute=0,
        args=[session_factory],
        id="purge_stale_events",
        misfire_grace_time=3600,
    )

    scheduler.start()

    # BackgroundAIWorker: claims pending events, investigates, dispatches to channel
    worker = BackgroundAIWorker(
        session_factory, investigation_service, settings, bot=bot
    )

    tasks = [
        asyncio.create_task(worker.run(stop_event)),
        asyncio.create_task(_alert_loop(session_factory, bot, settings)),
    ]

    # Store scheduler for shutdown
    tasks.append(asyncio.create_task(_run_scheduler(scheduler, stop_event)))

    return tasks


async def _run_scheduler(scheduler: AsyncIOScheduler, stop_event: asyncio.Event) -> None:
    """Run scheduler until stop_event is set."""
    while not stop_event.is_set():
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            break
    scheduler.shutdown(wait=False)


async def _alert_loop(session_factory, bot: Bot, settings: Settings) -> None:
    from whaledecode.jobs.send_alerts import send_alerts

    interval = settings.PAID_ALERT_BATCH_INTERVAL_SECONDS
    while True:
        try:
            await send_alerts(session_factory, bot, settings)
        except Exception as e:
            log.error("alert_loop_error", error=str(e))
            capture_exception(e)
        await asyncio.sleep(interval)


async def _run_briefing(session_factory, bot: Bot, settings: Settings) -> None:
    from whaledecode.jobs.daily_briefing import run_daily_briefing
    await run_daily_briefing(session_factory, bot, settings)


async def _purge_stale_events(session_factory) -> None:
    from whaledecode.adapters.db.uow import UnitOfWork

    async with UnitOfWork(session_factory) as uow:
        purged = await uow.candidate_events.purge_stale_events(days=3)
        await uow.commit()
    log.info("purged_stale_events", count=purged)


async def _reset_daily_counters(session_factory) -> None:
    from sqlalchemy import update
    from whaledecode.adapters.db.models.user import UserModel

    async with session_factory() as session:
        stmt = update(UserModel).values(daily_chat_count=0, daily_alert_count=0)
        await session.execute(stmt)
        await session.commit()
    log.info("daily_counters_reset")
