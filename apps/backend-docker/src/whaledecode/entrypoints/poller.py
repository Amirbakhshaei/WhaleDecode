"""Dedicated Targeted Failover Poller entrypoint (the Bulkhead).

Runs in its OWN process and event loop — deliberately isolated from the bot
and AI worker. If public RPC nodes melt down, if httpx hangs, or if this
process OOMs, Telegram command handling and alert dispatch keep running
untouched; only ingestion pauses. Handoff to the pipeline is the
``candidate_events`` table (INSERT ... ON CONFLICT DO NOTHING), so this
service needs no knowledge of — and no connection to — downstream consumers.

Run standalone: ``python -m whaledecode.entrypoints.poller``
Or via the CLI:  ``whaledecode poller``
"""
import asyncio
import signal

import structlog
from whaledecode.adapters.db.session import create_session_factory
from whaledecode.application.targeted_poller import TargetedPollerService
from whaledecode.config.settings import Settings
from whaledecode.infrastructure.telemetry import init_sentry

log = structlog.get_logger()


async def run_poller(settings: Settings) -> None:
    """Own the poller's lifecycle: startup, signal-bounded loop, clean teardown."""
    init_sentry(settings)
    session_factory = create_session_factory(settings)
    service = TargetedPollerService(session_factory, settings)

    stop_event = asyncio.Event()

    def shutdown(sig: int) -> None:
        log.info("poller_shutdown_signal", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: shutdown(s))
        except NotImplementedError:
            pass

    log.info("poller_started")
    try:
        await service.run(stop_event)
    finally:
        await service.aclose()
        await session_factory.dispose()
        log.info("poller_stopped")


def main() -> None:
    settings = Settings()
    from whaledecode.config.logging import setup_logging

    setup_logging(settings)
    asyncio.run(run_poller(settings))


if __name__ == "__main__":
    main()
