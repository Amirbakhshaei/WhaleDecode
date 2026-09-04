"""Dedicated Targeted Failover Poller entrypoint (the Bulkhead).

Runs in its OWN process and event loop — deliberately isolated from the bot
and AI worker. If public RPC nodes melt down, if httpx hangs, or if this
process OOMs, Telegram command handling and alert dispatch keep running
untouched; only ingestion pauses. Handoff to the pipeline is the
``candidate_events`` table (INSERT ... ON CONFLICT DO NOTHING), so this
service needs no knowledge of — and no connection to — downstream consumers.

A minimal HTTP ``/health`` endpoint runs alongside the loop so platform
healthchecks (railway.json applies ``healthcheckPath`` to every service
built from this image) see a live process even though this service is
purely a background poller.

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


async def _run_health_server(settings: Settings) -> None:
    """Tiny /health responder so platform probes pass for this HTTP-less service."""
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI()

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "service": "targeted-poller"}

    config = uvicorn.Config(app, host="0.0.0.0", port=settings.PORT, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()


async def run_poller(settings: Settings) -> None:
    """Own the poller's lifecycle: startup, signal-bounded loop, clean teardown."""
    init_sentry(settings)
    session_factory = create_session_factory(settings)
    from whaledecode.adapters.chain.factory import build_resilient_rpc

    rpc_manager = build_resilient_rpc(settings)
    service = TargetedPollerService(session_factory, settings, rpc_manager=rpc_manager)

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

    # Health server runs concurrently with the poll loop; SIGTERM stops both.
    health_task = asyncio.create_task(_run_health_server(settings))

    log.info("poller_started")
    try:
        await service.run(stop_event)
    finally:
        stop_event.set()
        await service.aclose()
        await session_factory.dispose()
        health_task.cancel()
        await asyncio.gather(health_task, return_exceptions=True)
        log.info("poller_stopped")

def main() -> None:
    settings = Settings()
    from whaledecode.config.logging import setup_logging

    setup_logging(settings)
    asyncio.run(run_poller(settings))


if __name__ == "__main__":
    main()
