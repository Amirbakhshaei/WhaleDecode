from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from whaledecode.adapters.db.models import Base
from whaledecode.adapters.db.repositories.curated_wallet import reset_wallet_cache
from whaledecode.infrastructure.http import HttpClientManager


@pytest.fixture(autouse=True)
def _clear_wallet_cache():
    """Clear wallet cache before each test to avoid cross-test pollution."""
    reset_wallet_cache()
    yield


@pytest.fixture(autouse=True)
def _clear_http_client_manager():
    """Reset the process-wide HTTP client pool so per-test httpx mocks apply cleanly."""
    yield
    HttpClientManager._clients.clear()


@pytest.fixture
def sample_address() -> str:
    return "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18"


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine("sqlite+aiosqlite://", echo=False, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()
