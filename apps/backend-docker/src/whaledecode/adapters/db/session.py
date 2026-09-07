import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from whaledecode.adapters.db.models import Base
from whaledecode.config.settings import Settings

# ponytail: worker polls every few seconds; silence SQLAlchemy's per-statement
# INFO logs in prod so they don't flood deployment logs (app logs stay at INFO).
_SQLALCHEMY_NOISY_LOGGERS = ("sqlalchemy.engine", "sqlalchemy.pool")


def create_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    url = settings.DATABASE_URL
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(
        url,
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=1800,
        pool_pre_ping=True,
        # ponytail: echo permanently off — multiline SQL statements flooded the
        # log stream and duplicated everything structlog already emits.
        connect_args={"timeout": 10},
    )
    if settings.ENV != "dev":
        for name in _SQLALCHEMY_NOISY_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)
    return async_sessionmaker(engine, expire_on_commit=False)


async def ensure_tables(settings: Settings) -> None:
    """Belt-and-suspenders table creation for fresh deploys.

    Idempotent — Alembic migrations are the source of truth, but if a deploy
    runs without ``db-init`` (e.g. the FastAPI replica before the release
    command completes), ``wallet_profiles`` etc. won't exist and the worker's
    first claim crashes with ``UndefinedTableError``. ``create_all`` is a
    no-op when the schema is already there.
    """
    url = settings.DATABASE_URL
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


async def get_session(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    async with factory() as session:
        yield session
