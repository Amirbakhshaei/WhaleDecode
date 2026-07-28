import asyncio
import signal

import structlog

from whaledecode.config.settings import Settings


async def run_worker(settings: Settings) -> None:
    log = structlog.get_logger()
    log.info("worker_not_implemented", env=settings.ENV)
    # ponytail: Phase 7 background workers stubbed — add polling/briefing jobs when needed
