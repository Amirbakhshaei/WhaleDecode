import asyncio

import click

from whaledecode import __version__
from whaledecode.config.logging import setup_logging
from whaledecode.config.settings import Settings


@click.group()
@click.version_option(version=__version__, prog_name="whaledecode")
def cli():
    """WhaleAgent v0.1 — AI Smart Money Agent."""


def _load_settings() -> Settings:
    try:
        settings = Settings()
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


@cli.command()
def bot():
    """Start Telegram bot (polling mode)."""
    settings = _load_settings()
    setup_logging(settings)

    import structlog

    log = structlog.get_logger()
    log.info("starting_bot", env=settings.ENV)

    if not settings.BOT_TOKEN.get_secret_value():
        raise click.ClickException("BOT_TOKEN is not set in .env")

    from whaledecode.entrypoints.bot import run_bot

    asyncio.run(run_bot(settings))


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
    if settings.ENV != "dev" and "sslmode" not in url:
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

    from scripts.seed import run_seed

    asyncio.run(run_seed(settings))


@cli.command()
def db_init():
    """Run migrations then seed database."""
    settings = _load_settings()
    setup_logging(settings)
    ctx = click.get_current_context()
    ctx.invoke(migrate)
    ctx.invoke(seed)


if __name__ == "__main__":
    cli()
