import asyncio
import os
import sys
from pathlib import Path

import click
from pydantic import SecretStr
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


def load_label_settings() -> Settings:
    """Settings for the standalone label cache (no Postgres / Telegram / LLM required).

    Label ingestion only needs GITHUB_TOKEN, LABELS_DB_PATH and the per-chain RPC URLs.
    The full Settings() model mandates BOT_TOKEN/GROQ_API_KEY/DATABASE_URL, which are
    irrelevant here, so we feed harmless placeholders only when those env vars are absent
    — letting the command run in any environment (e.g. a Railway console) without them."""
    kwargs: dict[str, SecretStr] = {}
    if not os.getenv("BOT_TOKEN"):
        kwargs["BOT_TOKEN"] = SecretStr("")
    if not os.getenv("GROQ_API_KEY"):
        kwargs["GROQ_API_KEY"] = SecretStr("")
    return Settings(**kwargs)


@cli.command()
def serve():
    """Run FastAPI app (Telegram bot + webhook server) via Uvicorn."""
    settings = _load_settings()
    setup_logging(settings)

    if not settings.BOT_TOKEN.get_secret_value():
        raise click.ClickException("BOT_TOKEN is not set in .env")

    import uvicorn
    uvicorn.run(
        "whaledecode.entrypoints.webhook:app",
        host="0.0.0.0",
        port=settings.PORT,
        log_level=settings.LOG_LEVEL.lower(),
    )


@cli.command()
def worker():
    """Start background worker (arq + APScheduler)."""
    settings = _load_settings()
    setup_logging(settings)

    import structlog

    log = structlog.get_logger()
    log.info("starting_worker", env=settings.ENV)

    from whaledecode.entrypoints.worker import run_worker

    asyncio.run(run_worker(settings))


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

    from alembic import command
    from alembic.config import Config

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
@click.option("--db", default=None, help="SQLite path (defaults to settings.LABELS_DB_PATH)")
@click.option("--repos", default=None, help="Comma-separated owner/repo overrides")
@click.option("--token", default=None, help="GitHub PAT (else settings.GITHUB_TOKEN / GITHUB_TOKEN env)")
def ingest_labels(db: str | None, repos: str | None, token: str | None) -> None:
    """Ingest public EVM address labels into the SQLite cache (on demand)."""
    settings = load_label_settings()
    setup_logging(settings)

    # Ensure output is never swallowed by block-buffering when stdout isn't a TTY
    # (piped CI logs, Railway console capture) — otherwise the command looks silent.
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:  # noqa: BLE001 - not all streams support reconfigure
        pass

    from whaledecode.label_ingestion.config import DEFAULT_REPO_TARGETS, RepoTarget
    from whaledecode.label_ingestion.main import run

    db_path = db or settings.LABELS_DB_PATH
    targets = (
        [RepoTarget(r.strip()) for r in repos.split(",") if r.strip()]
        if repos
        else list(DEFAULT_REPO_TARGETS)
    )
    gh_token = token or (
        settings.GITHUB_TOKEN.get_secret_value() if settings.GITHUB_TOKEN else None
    )
    rpc_urls = {
        int(c): u
        for c, u in (
            (1, settings.ETH_RPC_URL),
            (42161, settings.ARB_RPC_URL),
            (8453, settings.BASE_RPC_URL),
        )
        if u
    }
    click.echo(f"▶ ingesting {len(targets)} repos -> {db_path}")
    sys.stdout.flush()
    try:
        stats = asyncio.run(run(targets, db_path, gh_token, rpc_urls))
    except Exception as exc:  # noqa: BLE001 - surface the real error instead of exiting silently
        click.echo(f"✗ ingest failed: {exc}", err=True)
        sys.exit(1)

    click.echo(
        f"Ingested: files={stats.files} records={stats.records} "
        f"stored={stats.stored} skipped={stats.skipped} -> {db_path}"
    )
    for f in stats.failures:
        click.echo(f"  ! failed: {f}")
    if stats.stored == 0:
        click.echo("✗ nothing stored — check GITHUB_TOKEN and that the repos expose label files.", err=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()
