from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from whaledecode.config.settings import Settings


def create_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    url = settings.DATABASE_URL
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if settings.ENV != "dev" and "sslmode" not in url:
        url += "&sslmode=require" if "?" in url else "?sslmode=require"
    engine = create_async_engine(
        url,
        pool_size=settings.DATABASE_POOL_SIZE,
        echo=settings.ENV == "dev",
    )
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    async with factory() as session:
        yield session
