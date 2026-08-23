"""Tests for the Active-Trigger extraction/sync scripts and case-insensitive lookups."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import SecretStr

# Top-level scripts/ live outside the whaledecode package; make them importable.
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from whaledecode.adapters.db.models import Base  # noqa: E402
from whaledecode.adapters.db.models.curated_wallet import CuratedWalletModel  # noqa: E402
from whaledecode.adapters.db.repositories.curated_wallet import (  # noqa: E402
    CuratedWalletRepository,
)
from whaledecode.domain.entities.curated_wallet import CuratedWallet  # noqa: E402
from whaledecode.domain.value_objects.chain import Chain  # noqa: E402


@pytest.mark.asyncio
async def test_get_by_address_and_chain_case_insensitive(db_session):
    """Lookups normalize address (lower) and chain (upper) before comparing."""
    db_session.add(
        CuratedWalletModel(
            address="0xABCDEF0000000000000000000000000000000001",
            chain="eth",
            label="Mixed Case",
            category="Smart Money",
            is_active=True,
            quality_score=90.0,
        )
    )
    await db_session.commit()

    repo = CuratedWalletRepository(db_session)
    found = await repo.get_by_address_and_chain(
        "0xabcdef0000000000000000000000000000000001", "ETH"
    )
    assert found is not None
    assert found.label == "Mixed Case"


async def _seed_curated(session, rows: list[dict]) -> None:
    for r in rows:
        session.add(
            CuratedWalletModel(
                address=r["address"],
                chain=r["chain"],
                label=r.get("label", ""),
                category=r["category"],
                is_active=r.get("is_active", True),
                quality_score=r["quality_score"],
            )
        )
    await session.commit()


@pytest.mark.asyncio
async def test_extract_active_wallets_filters_high_conviction(tmp_path, monkeypatch):
    """Only Smart Money / Notable Whale with score>=80 are exported, lowercased."""
    import extract_active_wallets as ext
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    db_url = f"sqlite+aiosqlite:///{tmp_path/'db.sqlite'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await _seed_curated(
            s,
            [
                {"address": "0x" + "A1" * 20, "chain": "ETH", "category": "Smart Money", "quality_score": 95.0},
                {"address": "0x" + "B2" * 20, "chain": "ARB", "category": "Notable Whale", "quality_score": 82.0},
                {"address": "0x" + "C3" * 20, "chain": "ETH", "category": "Smart Money", "quality_score": 79.0},  # too low
                {"address": "0x" + "D4" * 20, "chain": "ETH", "category": "Bridge", "quality_score": 99.0},  # excluded cat
                {"address": "0x" + "E5" * 20, "chain": "ETH", "category": "Smart Money", "quality_score": 88.0, "is_active": False},  # inactive
            ],
        )

    out = tmp_path / "alchemy_webhook_wallets.json"
    monkeypatch.setattr(ext, "_OUTPUT_PATH", out)
    wallets = await ext.extract()
    ext._write_export(wallets, out)

    assert len(wallets) == 2
    assert all(w["address"] == w["address"].lower() for w in wallets)
    assert {w["category"] for w in wallets} <= {"Smart Money", "Notable Whale"}
    assert out.exists()
    on_disk = json.loads(out.read_text())
    assert len(on_disk) == 2


@pytest.mark.asyncio
async def test_sync_alchemy_webhook_diff_and_patch(tmp_path, monkeypatch):
    """Sync adds new trigger wallets and removes stale ones via batched PATCH."""
    import sync_alchemy_webhook as sync

    # Fake input JSON.
    in_file = tmp_path / "alchemy_webhook_wallets.json"
    in_file.write_text(json.dumps([{"address": "0x" + "A1" * 20}, {"address": "0x" + "B2" * 20}]))

    # Fake Settings (token must be a SecretStr for _auth_token).
    class _FakeSettings:
        ALCHEMY_API_KEY = SecretStr("test-token")
        ALCHEMY_NOTIFY_TOKEN = None
        ALCHEMY_AUTH_TOKEN = None
        ALCHEMY_WEBHOOK_ID = "wh_test"
        ALCHEMY_WEBHOOK_ID_ETH = "wh_test"

    monkeypatch.setattr(sync, "Settings", lambda: _FakeSettings())
    monkeypatch.setattr(sync, "_INPUT_PATH", in_file)

    # Mock HTTP client: currently holds B2 + an old C3.
    patches: list[dict] = []

    class _Resp:
        def __init__(self, status, text=""):
            self.status_code = status
            self.text = text
            self._json = {"data": ["0x" + "b2" * 20, "0x" + "c3" * 20], "pagination": {}}

        @property
        def is_success(self):
            return 200 <= self.status_code < 300

        def json(self):
            return self._json

    class _Client:
        async def get(self, *a, **k):
            return _Resp(200)

        async def patch(self, url, headers=None, json=None):
            patches.append(json)
            return _Resp(200)

    monkeypatch.setattr(sync.HttpClientManager, "get_client", staticmethod(lambda *a, **k: _Client()))

    added, removed = await sync.sync("wh_test", ["0x" + "a1" * 20, "0x" + "b2" * 20])

    assert added == 1  # A1 added
    assert removed == 1  # C3 removed
    # Single batch covers both add and remove.
    assert len(patches) == 1
    assert "0x" + "a1" * 20 in patches[0]["addresses_to_add"]
    assert "0x" + "c3" * 20 in patches[0]["addresses_to_remove"]


@pytest.mark.asyncio
async def test_global_min_alert_threshold_lifts_base_floor(monkeypatch):
    """MIN_ALERT_USD_THRESHOLD (50k) overrides BASE's lower 30k chain floor."""
    import whaledecode.entrypoints.webhook as webhook

    wallet = CuratedWallet(id=1, address="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18", chain=Chain.BASE, label="Whale")
    # 40k USD move: clears BASE's 30k floor but fails the global 50k gate.
    data = webhook._build_candidate_data(_erc20_activity(1000.0), Chain.BASE, wallet)
    monkeypatch.setattr(webhook, "_price_oracle", _FakeOracle(40.0))

    assert await webhook._clears_chain_floor(data, min_usd_threshold=50_000.0) is False
    assert data["raw_json"]["value_usd"] == 40_000.0

    # 60k move clears both gates.
    data2 = webhook._build_candidate_data(_erc20_activity(1000.0), Chain.BASE, wallet)
    monkeypatch.setattr(webhook, "_price_oracle", _FakeOracle(60.0))
    assert await webhook._clears_chain_floor(data2, min_usd_threshold=50_000.0) is True


class _FakeOracle:
    def __init__(self, price: float) -> None:
        self._price = price

    async def get_token_price_usd(self, contract_address: str, chain: str) -> float:
        return self._price


def _erc20_activity(value: float) -> dict:
    return {
        "blockNum": "0xdf34a3",
        "hash": "0x" + "c" * 64,
        "fromAddress": "0x503828976d22510aad0201ac7ec88293211d23da",
        "toAddress": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18",
        "value": value,
        "asset": "WETH",
        "category": "external",
        "log": {},
    }
