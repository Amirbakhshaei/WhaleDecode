import json
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whaledecode.adapters.db.models import Base


@pytest.mark.asyncio
async def test_ensure_curated_wallets_seeded():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    wallets_path = Path(__file__).resolve().parent.parent.parent / "data" / "wallets_seed.json"
    assert wallets_path.exists(), f"wallets_seed.json not found at {wallets_path}"

    with open(wallets_path) as f:
        wallets_data = json.load(f)
    assert len(wallets_data) > 0, "wallets_seed.json is empty"

    from whaledecode.entrypoints.seed import ensure_curated_wallets_seeded
    await ensure_curated_wallets_seeded(factory)

    from whaledecode.adapters.db.repositories.curated_wallet import CuratedWalletRepository
    from whaledecode.domain.value_objects.chain import Chain
    async with factory() as session:
        repo = CuratedWalletRepository(session)
        wallets = await repo.list_active()
        assert len(wallets) == len(wallets_data), f"Expected {len(wallets_data)} wallets, got {len(wallets)}"
        assert all(w.label for w in wallets), "All seeded wallets must have labels"
        assert all(w.address.startswith("0x") for w in wallets), "All wallets must have valid hex addresses"

        eth_count = sum(1 for w in wallets if w.chain == Chain.ETH)
        base_count = sum(1 for w in wallets if w.chain == Chain.BASE)
        arb_count = sum(1 for w in wallets if w.chain == Chain.ARB)
        assert eth_count > 0, "No ETH wallets seeded"
        assert base_count > 0, "No BASE wallets seeded"
        assert arb_count > 0, "No ARB wallets seeded"

    await engine.dispose()
