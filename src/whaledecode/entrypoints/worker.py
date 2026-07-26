import asyncio

import structlog

from whaledecode.config.settings import Settings


async def run_worker(settings: Settings) -> None:
    log = structlog.get_logger()
    log.info("worker_started")

    # Phase 7: will initialize arq Worker + APScheduler here
    await asyncio.Future()  # run forever
