import asyncio

import structlog
from arq import create_pool
from arq.connections import RedisSettings

from whaledecode.config.settings import Settings
from whaledecode.jobs import batch_dispatch_alerts, generate_daily_briefing, poll_events

REDIS_HEALTH_CHECK_INTERVAL = 30


async def startup(ctx: dict) -> None:
    log = structlog.get_logger()
    ctx["log"] = log
    log.info("worker_startup")


async def shutdown(ctx: dict) -> None:
    log = structlog.get_logger()
    log.info("worker_shutdown")


class WorkerSettings:
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn("redis://localhost:6379")
    keep_result = 300
    max_jobs = 10
    job_timeout = 120
    functions = [poll_events, batch_dispatch_alerts, generate_daily_briefing]


async def run_worker(settings: Settings) -> None:
    log = structlog.get_logger()
    log.info("worker_starting", redis_url=settings.REDIS_URL)

    _redis = await create_pool(
        RedisSettings.from_dsn(settings.REDIS_URL),
        health_check_interval=REDIS_HEALTH_CHECK_INTERVAL,
    )

    async def cron_poll():
        while True:
            await poll_events({})
            await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)

    async def cron_briefing():
        while True:
            now = asyncio.get_event_loop().time()
            next_run = ((now // 86400) + 1) * 86400
            await asyncio.sleep(next_run - now)
            await generate_daily_briefing({})

    log.info("worker_running")
    await asyncio.gather(cron_poll(), cron_briefing(), return_exceptions=True)
