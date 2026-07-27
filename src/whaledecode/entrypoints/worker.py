import asyncio
import signal

import structlog

from whaledecode.config.settings import Settings
from whaledecode.jobs import generate_daily_briefing, poll_events


async def run_worker(settings: Settings) -> None:
    log = structlog.get_logger()
    log.info("worker_starting")

    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        log.info("worker_signal_received")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    async def cron_poll():
        while not stop_event.is_set():
            try:
                await poll_events({})
            except Exception as e:
                log.error("cron_poll_error", error=str(e))
            await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)

    async def cron_briefing():
        while not stop_event.is_set():
            try:
                now = loop.time()
                next_run = ((now // 86400) + 1) * 86400
                wait = next_run - now
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=wait)
                    return
                except TimeoutError:
                    pass
                await generate_daily_briefing({})
            except Exception as e:
                log.error("cron_briefing_error", error=str(e))

    log.info("worker_running")
    tasks = [asyncio.create_task(cron_poll()), asyncio.create_task(cron_briefing())]

    try:
        await stop_event.wait()
    finally:
        log.info("worker_shutdown_start")
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        log.info("worker_shutdown_complete")
