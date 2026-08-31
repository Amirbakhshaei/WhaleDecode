import asyncio
from pathlib import Path

import click

from whaledecode import __version__
from whaledecode.config.logging import setup_logging
from whaledecode.config.settings import Settings


@click.group()
@click.version_option(version=__version__, prog_name="whaledecode")
def cli():
    """WhaleDecode — AI Smart Money Agent."""


def _load_settings() -> Settings:
    try:
        settings = Settings()
        settings.inject_langsmith_env()
    except Exception as e:
        raise click.ClickException(
            f"Missing or invalid env vars:\n{e}\n\n"
            "Copy .env.example to .env and fill in the required values."
        )
    if not settings.DATABASE_URL:
        raise click.ClickException(
            "DATABASE_URL is not set.\n\n"
            "On Railway: add the Postgres plugin (it injects DATABASE_URL automatically).\n"
            "Locally: set DATABASE_URL in .env (see .env.example)."
        )
    return settings


def _check_rpc_isolation(settings: Settings) -> None:
    """Warn loudly if any on-chain RPC URL points at Alchemy.

    RPC telemetry (eth_getBalance, Multicall3, …) bills CUs on Alchemy; it must
    route to a dedicated RPC provider (e.g. dRPC) so the CU budget is reserved
    for webhook delivery only.
    """
    rpc_urls = [
        ("ETH_RPC_URL", settings.ETH_RPC_URL),
        ("ARB_RPC_URL", settings.ARB_RPC_URL),
        ("BASE_RPC_URL", settings.BASE_RPC_URL),
    ]
    for name, url in rpc_urls:
        if url and "alchemy.com" in str(url).lower():
            raise click.ClickException(
                f"CRITICAL CONFIG ERROR: {name} points at Alchemy ({url!r}).\n"
                "RPC telemetry must route to a dedicated provider (e.g. dRPC) to prevent CU exhaustion."
            )


@cli.command()
def serve():
    """Run FastAPI app (Telegram bot + webhook server) via Uvicorn."""
    import sys

    print("whaledecode serve: starting", file=sys.stderr, flush=True)
    settings = _load_settings()
    _check_rpc_isolation(settings)
    setup_logging(settings)

    if not settings.BOT_TOKEN.get_secret_value():
        raise click.ClickException("BOT_TOKEN is not set in .env")
    import uvicorn

    uvicorn.run(
        "whaledecode.entrypoints.webhook:app",
        host="0.0.0.0",
        port=settings.PORT,
        log_level=settings.LOG_LEVEL.lower(),
        workers=1,  # single process per replica; Telegram pushes via /webhook/telegram (stateless)
    )


def _alembic_url(settings: Settings) -> str:
    url = settings.DATABASE_URL
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    from sqlalchemy.engine.url import make_url

    parsed_url = make_url(url)
    host = parsed_url.host or ""
    is_internal_host = host in ["localhost", "127.0.0.1", "postgres"] or host.endswith(".railway.internal")

    if settings.ENV != "dev" and "sslmode" not in url and not is_internal_host:
        url += "&sslmode=require" if "?" in url else "?sslmode=require"

    return url


@cli.command()
def migrate():
    """Run Alembic database migrations."""
    settings = _load_settings()
    setup_logging(settings)

    from alembic.config import Config

    from alembic import command

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", _alembic_url(settings))
    command.upgrade(cfg, "head")


@cli.command()
def seed():
    """Seed database with curated wallets and demo events."""
    settings = _load_settings()
    setup_logging(settings)

    from whaledecode.entrypoints.seed import run_seed

    asyncio.run(run_seed(settings))


@cli.command()
def db_init():
    """Run migrations then seed database."""
    import sys

    print("whaledecode db-init: starting", file=sys.stderr, flush=True)
    settings = _load_settings()
    setup_logging(settings)
    ctx = click.get_current_context()
    ctx.invoke(migrate)
    ctx.invoke(seed)


@cli.command()
def verify_seed():
    """Verify seed wallet addresses have on-chain activity (writes wallets_verified.json)."""
    settings = _load_settings()
    setup_logging(settings)

    from whaledecode.scripts.verify_seed import main as verify_main

    exit(verify_main())


@cli.command()
def unstick() -> None:
    """Purge stale pending alerts and re-queue candidate events from the last 24h so
    they re-run through the current EventGate and channel formatter."""
    settings = _load_settings()
    setup_logging(settings)

    from whaledecode.adapters.db.session import create_session_factory
    from whaledecode.adapters.db.uow import UnitOfWork

    async def _unstick() -> tuple[int, int]:
        factory = create_session_factory(settings)
        async with UnitOfWork(factory) as uow:
            purged = await uow.alerts.purge_pending()
            requeued = await uow.candidate_events.requeue_recent_events(hours=24)
            await uow.commit()
        return purged, requeued

    purged, requeued = asyncio.run(_unstick())
    click.echo(f"Purged {purged} stale pending alerts; re-queued {requeued} candidate events.")


@cli.command()
@click.option("--webhook-id", required=True, help="Alchemy webhook ID (wh_...)")
@click.option("--verified-file", required=True, type=click.Path(exists=True), help="Path to wallets_verified.json")
def sync_webhook(webhook_id: str, verified_file: str):
    """Sync verified addresses to an Alchemy webhook via Notify API."""
    settings = _load_settings()
    setup_logging(settings)

    import asyncio

    from whaledecode.scripts.verify_seed import sync_webhook as sync_impl

    exit(asyncio.run(sync_impl(webhook_id, Path(verified_file))))


@cli.command()
@click.option("--dry-run", is_flag=True, help="Replay the candidate→investigation→channel pipeline in memory")
@click.option("--event-id", type=int, default=None, help="Target a specific candidate event for the dry run")
def debug_pipeline(dry_run: bool, event_id: int | None):
    """Inspect candidate/alert/agent_run state, or trace the pipeline for one event."""
    settings = _load_settings()
    setup_logging(settings)

    from whaledecode.cli.debug_pipeline import main as debug_main

    argv = []
    if dry_run:
        argv.append("--dry-run")
    if event_id is not None:
        argv += ["--event-id", str(event_id)]
    exit(debug_main(argv))


@cli.command()
def prune_alchemy_webhooks():
    """Remove blacklisted high-frequency addresses (tokens, routers, CEX sweepers) from Alchemy webhooks."""
    settings = _load_settings()
    setup_logging(settings)

    from whaledecode.cli.prune_alchemy_webhooks import run_pruner

    exit(asyncio.run(run_pruner()))


@cli.command()
def sync_curated():
    """Sync curated entities (Dune baseline + DefiLlama) into Postgres + Alchemy."""
    from whaledecode.cli.sync_curated_entities import run_sync_pipeline

    asyncio.run(run_sync_pipeline())


if __name__ == "__main__":
    cli()
