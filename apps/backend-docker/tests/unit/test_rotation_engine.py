"""Tests for the 300-wallet rotation engine and ingestion decoder."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from whaledecode.adapters.db.models.curated_wallet import CuratedWalletModel
from whaledecode.adapters.db.repositories.curated_wallet import CuratedWalletRepository
from whaledecode.config.settings import Settings
from whaledecode.services import decoder, webhook_rotator
from whaledecode.services.webhook_rotator import WebhookRotationService

A_H0 = "0x" + "h0" * 20
A_C0 = "0x" + "c0" * 20
A_A0 = "0x" + "a0" * 20
A_G0 = "0x" + "g0" * 20
A_E0 = "0x" + "e0" * 20
A_I0 = "0x" + "i0" * 20
A_B2 = "0x" + "b2" * 20
A_C3 = "0x" + "c3" * 20
A_A1 = "0x" + "a1" * 20
A_V1 = "0x" + "v1" * 20
A_V2 = "0x" + "v2" * 20
A_R1 = "0x" + "r1" * 20
A_DEAD = "0x" + "dead" * 20


def _seed(session, rows):
    for r in rows:
        session.add(
            CuratedWalletModel(
                address=r["address"],
                chain=r.get("chain", "ETH"),
                label=r.get("label", ""),
                category=r["category"],
                is_active=r.get("is_active", True),
                quality_score=r["quality_score"],
                tx_count_30d=r.get("tx", 0),
                velocity_penalty=r.get("vp", 1.0),
                is_monitored_active=r.get("monitored", False),
            )
        )


def _settings():
    s = Settings()
    s.ALCHEMY_API_KEY = None
    s.ALCHEMY_NOTIFY_TOKEN = None
    s.ALCHEMY_AUTH_TOKEN = None
    s.ALCHEMY_WEBHOOK_ID = ""
    s.ALCHEMY_WEBHOOK_ID_ETH = ""
    return s


class _Factory:
    """Session factory that always yields the same injected test session."""

    def __init__(self, session):
        self._session = session

    def __call__(self):
        return _SessionCtx(self._session)


class _SessionCtx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_set_monitored_flags_reconciles(db_session):
    _seed(
        db_session,
        [
            {"address": A_A1, "category": "Smart Money", "quality_score": 90.0, "monitored": True},
            {"address": A_B2, "category": "Smart Money", "quality_score": 90.0, "monitored": True},
            {"address": A_C3, "category": "Smart Money", "quality_score": 90.0, "monitored": True},
        ],
    )
    await db_session.commit()

    repo = CuratedWalletRepository(db_session)
    await repo.set_monitored_flags({A_A1, A_C3})
    await db_session.commit()

    rows = (await db_session.execute(select(CuratedWalletModel))).scalars().all()
    flags = {r.address.lower(): r.is_monitored_active for r in rows}
    assert flags[A_A1] is True
    assert flags[A_C3] is True
    assert flags[A_B2] is False


@pytest.mark.asyncio
async def test_select_top_candidates_velocity_and_filters(db_session):
    _seed(
        db_session,
        [
            {"address": A_H0, "category": "Smart Money", "quality_score": 100.0, "vp": 1.0},
            {"address": A_C0, "category": "VC Fund", "quality_score": 95.0, "vp": 1.0},
            {"address": A_A0, "category": "Notable Whale", "quality_score": 90.0, "vp": 1.0},
            {"address": A_G0, "category": "Smart Money", "quality_score": 100.0, "vp": 0.2},
            {"address": A_E0, "category": "Bridge", "quality_score": 999.0},
            {"address": A_I0, "category": "Smart Money", "quality_score": 100.0, "tx": 700},
        ],
    )
    await db_session.commit()

    svc = WebhookRotationService(_settings(), _Factory(db_session), auth_token="tok", webhook_id="wh_1")
    top = await svc.select_top_candidates(db_session, total_limit=3)
    assert [w["address"] for w in top] == [A_H0, A_C0, A_A0]
    addresses = [w["address"] for w in top]
    assert A_G0 not in addresses  # velocity penalty dropped it
    assert A_E0 not in addresses  # excluded category
    assert A_I0 not in addresses  # tx_count_30d filter


@pytest.mark.asyncio
async def test_select_top_candidates_balances_chains(db_session):
    # 250 high-scoring ETH wallets plus 100 each on ARB/BASE. With a global
    # ORDER BY ... LIMIT 300 the ETH pool would starve the L2s; the per-chain
    # quotas must guarantee 180 ETH / 60 ARB / 60 BASE even when ETH outranks.
    rows = []
    for i in range(250):
        rows.append({"address": f"0xeth{i:039d}", "chain": "ETH", "category": "Smart Money", "quality_score": 100.0})
    for i in range(100):
        rows.append({"address": f"0xarb{i:039d}", "chain": "ARB", "category": "Smart Money", "quality_score": 100.0})
    for i in range(100):
        rows.append({"address": f"0xbase{i:038d}", "chain": "BASE", "category": "Smart Money", "quality_score": 100.0})
    _seed(db_session, rows)
    await db_session.commit()

    svc = WebhookRotationService(_settings(), _Factory(db_session), auth_token="tok", webhook_id="wh_1")
    top = await svc.select_top_candidates(db_session, total_limit=300)

    by_chain: dict[str, int] = {}
    for w in top:
        by_chain[w["chain"]] = by_chain.get(w["chain"], 0) + 1
    assert by_chain.get("ETH", 0) == 180
    assert by_chain.get("ARB", 0) == 60
    assert by_chain.get("BASE", 0) == 60
    assert len(top) == 300


@pytest.mark.asyncio
async def test_sync_rotation_cycle_patches_delta_and_flags(db_session, monkeypatch):
    _seed(
        db_session,
        [
            {"address": A_H0, "category": "Smart Money", "quality_score": 100.0},
            {"address": A_A0, "category": "Notable Whale", "quality_score": 90.0},
        ],
    )
    await db_session.commit()

    patches = []

    class _Client:
        async def get(self, url, headers=None, params=None):
            return _Resp(200, {"data": [A_DEAD], "pagination": {}})

        async def patch(self, url, headers=None, json=None):
            patches.append(json)
            return _Resp(200)

    class _Resp:
        def __init__(self, status, json_body=None, text=""):
            self.status_code = status
            self.text = text
            self._json = json_body or {}

        @property
        def is_success(self):
            return 200 <= self.status_code < 300

        def json(self):
            return self._json

    monkeypatch.setattr(webhook_rotator.HttpClientManager, "get_client", staticmethod(lambda *a, **k: _Client()))

    svc = WebhookRotationService(_settings(), _Factory(db_session), auth_token="tok", webhook_id="wh_1")
    summary = await svc.sync_rotation_cycle(limit=300)

    assert summary["monitored"] == 2
    assert summary["added"] == 2
    assert summary["removed"] == 1
    assert len(patches) == 1
    assert A_DEAD in patches[0]["addresses_to_remove"]
    assert A_H0 in patches[0]["addresses_to_add"]

    rows = (await db_session.execute(select(CuratedWalletModel))).scalars().all()
    flags = {r.address.lower(): r.is_monitored_active for r in rows}
    assert flags[A_H0] is True
    assert flags[A_A0] is True


@pytest.mark.asyncio
async def test_velocity_telemetry_increments(db_session):
    _seed(db_session, [{"address": A_V1, "category": "Smart Money", "quality_score": 90.0, "tx": 0}])
    await db_session.commit()

    await decoder.apply_velocity_telemetry(db_session, [A_V1])
    await db_session.commit()
    stmt = select(CuratedWalletModel).execution_options(populate_existing=True)
    row = (await db_session.execute(stmt)).scalar_one()
    assert row.tx_count_30d == 1
    assert row.velocity_penalty == 1.0

    await decoder.apply_velocity_telemetry(db_session, [A_V1.upper()])
    await db_session.commit()
    row = (await db_session.execute(stmt)).scalar_one()
    assert row.tx_count_30d == 2


@pytest.mark.asyncio
async def test_velocity_penalty_kicks_in_above_400(db_session):
    _seed(db_session, [{"address": A_V2, "category": "Smart Money", "quality_score": 90.0, "tx": 401}])
    await db_session.commit()
    await decoder.apply_velocity_telemetry(db_session, [A_V2])
    await db_session.commit()
    stmt = select(CuratedWalletModel).execution_options(populate_existing=True)
    row = (await db_session.execute(stmt)).scalar_one()
    assert row.velocity_penalty == 0.2


def test_value_threshold():
    s = _settings()
    assert decoder.is_above_value_threshold(50_000.0, s) is True
    assert decoder.is_above_value_threshold(49_999.0, s) is False
    assert decoder.is_above_value_threshold(None, s) is False


@pytest.mark.asyncio
async def test_resolve_entity_case_insensitive(db_session):
    _seed(db_session, [{"address": A_R1, "category": "Smart Money", "quality_score": 90.0, "label": "Alpha Fund"}])
    await db_session.commit()
    entity = await decoder.resolve_entity(db_session, A_R1.upper())
    assert entity is not None
    assert entity.label == "Alpha Fund"
