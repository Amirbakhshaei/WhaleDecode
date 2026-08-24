"""Module 1: behavioral profiler pure computation + alert-time enrichment."""
import pytest
from whaledecode.services.behavioral_profiler import (
    BehavioralProfiler,
    compute_profile_from_ledger,
)

NOW = 1_000.0


def _event(token, ts, entry, amount=1.0, event_type="SWAP"):
    return {
        "event_type": event_type,
        "token": token,
        "token_amount": amount,
        "entry_price_usd": entry,
        "value_usd": entry * amount,
        "timestamp_unix": ts,
    }


def test_win_rate_counts_tokens_up_10pct():
    events = [
        _event("0xAAA", 10, 1.00),   # now 2.00 -> +100% win
        _event("0xBBB", 20, 1.00),   # now 1.20 -> +20% win
        _event("0xCCC", 30, 1.00),   # now 1.05 -> below threshold
        _event("0xDDD", 40, 2.00),   # now 1.00 -> -50% loss
    ]
    prices = {"0xaaa": 2.0, "0xbbb": 1.2, "0xccc": 1.05, "0xddd": 1.0}
    profile = compute_profile_from_ledger(events, prices)
    assert profile["sample_size_30d"] == 4
    assert profile["historical_win_rate_30d"] == pytest.approx(0.5)
    # +1.00 (AAA) +0.20 (BBB) -1.00 (DDD); CCC is flat so contributes nothing.
    assert profile["total_pnl_usd"] == pytest.approx(0.20)
    assert profile["primary_strategy"] == "DEX Scalper"


def test_first_accumulation_per_token_is_scored_not_repeats():
    events = [
        _event("0xAAA", 10, 1.00),
        _event("0xAAA", 500, 9.99),  # later buy must be ignored
    ]
    profile = compute_profile_from_ledger(events, {"0xaaa": 2.0})
    assert profile["historical_win_rate_30d"] == pytest.approx(1.0)


def test_empty_ledger_yields_nothing():
    assert compute_profile_from_ledger([], {}) == {}


@pytest.mark.asyncio
async def test_enrich_returns_empty_for_unknown_wallet(session_factory):
    calls = []

    def uow_factory():
        class FakeUow:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        class Repo:
            async def get(self, chain, address):
                calls.append((chain, address))
                return None

        fake = FakeUow()
        fake.wallet_profiles = Repo()
        return fake

    profiler = BehavioralProfiler(uow_factory)
    assert await profiler.enrich("base", "0xdead") == {}
    assert calls == [("base", "0xdead")]


@pytest.mark.asyncio
async def test_enrich_includes_win_rate_only_above_sample_floor(session_factory):
    from types import SimpleNamespace

    def uow_factory():
        class FakeUow:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        class Repo:
            async def get(self, chain, address):
                return SimpleNamespace(
                    primary_strategy="Spot Accumulator",
                    total_pnl_usd=1234.0,
                    recent_actions_summary="SWAP $50,000 0xAAA",
                    sample_size_30d=5,
                    historical_win_rate_30d=0.75,
                    avg_holding_period_days=3.0,
                )

        fake = FakeUow()
        fake.wallet_profiles = Repo()
        return fake

    ctx = await BehavioralProfiler(uow_factory).enrich("eth", "0xlive")
    assert ctx["wallet_win_rate_30d"] == 0.75
    assert "75%" in ctx["wallet_intent_hint"]
