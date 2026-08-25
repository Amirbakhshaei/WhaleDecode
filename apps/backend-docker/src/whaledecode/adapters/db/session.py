import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
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


async def get_session(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    async with factory() as session:
        yield session
