import pytest
from whaledecode.domain.entities.candidate_event import CandidateEvent
from whaledecode.domain.services.event_gate import (
    CRITICAL_EVENT_TYPES,
    MIN_WHALE_THRESHOLD_USD,
    EventGate,
    process_and_gate_candidate,
)
from whaledecode.domain.value_objects.hash import Hash

TX_HASH = "0x" + "b" * 64


class _FakeOracle:
    def __init__(self, price: float, historical: float | None = None) -> None:
        self.price = price
        self.historical = historical

    async def get_token_price_usd(self, contract_address: str, chain: str) -> float:
        return self.price

    async def get_token_price_usd_at(self, contract_address: str, chain: str, unix_ts: float) -> float:
        return self.historical if self.historical is not None else self.price


def _event(
    *,
    event_type: str = "TRANSFER",
    score: float = 0.9,
    value_usd: float = 0.0,
) -> CandidateEvent:
    raw_json = {"value_usd": value_usd} if value_usd else {}
    return CandidateEvent(
        wallet_id=1,
        chain="ETH",
        tx_hash=Hash(TX_HASH),
        log_index=0,
        block_number=100,
        event_type=event_type,
        raw_json=raw_json,
        score=score,
        dedupe_key="1:test",
    )


def test_high_score_event_passes_gate() -> None:
    gate = EventGate(min_score_threshold=0.65)
    assert gate.should_investigate(_event(score=0.9, value_usd=100_000.0))


def test_low_score_event_dropped() -> None:
    gate = EventGate(min_score_threshold=0.65)
    assert not gate.should_investigate(_event(score=0.1, value_usd=100_000.0))


def test_low_value_event_dropped() -> None:
    gate = EventGate(min_score_threshold=0.65)
    assert not gate.should_investigate(_event(score=0.9, value_usd=10_000.0))


def test_whale_threshold_is_hard_floor() -> None:
    # A lowered config value cannot soften the $50k floor.
    gate = EventGate(min_score_threshold=0.65, min_value_usd=1000.0)
    assert not gate.should_investigate(_event(score=0.9, value_usd=49_999.99))
    # $50k exactly should pass
    assert gate.should_investigate(_event(score=0.9, value_usd=50_000.0))


def test_zero_value_event_dropped() -> None:
    gate = EventGate(min_score_threshold=0.65)
    event = _event(score=0.9)
    event.raw_json["value_usd"] = 0.0
    assert not gate.should_investigate(event)


def test_missing_value_usd_dropped() -> None:
    gate = EventGate(min_score_threshold=0.65)
    event = _event(score=0.9)
    assert "value_usd" not in event.raw_json
    assert not gate.should_investigate(event)


def test_high_value_event_passes() -> None:
    gate = EventGate(min_score_threshold=0.65)
    assert gate.should_investigate(_event(score=0.9, value_usd=100_000.0))


def test_string_value_usd_is_tolerated() -> None:
    gate = EventGate(min_score_threshold=0.65)
    event = _event(score=0.9)
    event.raw_json["value_usd"] = "1000.0"
    assert not gate.should_investigate(event)
    event.raw_json["value_usd"] = "100000.0"
    assert gate.should_investigate(event)


def test_malformed_value_usd_dropped() -> None:
    gate = EventGate(min_score_threshold=0.65)
    event = _event(score=0.9)
    event.raw_json["value_usd"] = {"nested": True}
    assert not gate.should_investigate(event)


def test_is_above_floor_string_comparison() -> None:
    """Test that string values are properly cast to float before comparison."""
    from whaledecode.domain.services.event_gate import is_above_floor
    # String "101147.87" should be correctly compared as float
    assert is_above_floor("101147.87", 50_000.0) is True
    assert is_above_floor("49999.99", 50_000.0) is False
    # String "100000.0" with floor 50000
    assert is_above_floor("100000.0", 50000.0) is True
    # None value should be treated as 0.0
    assert is_above_floor(None, 50_000.0) is False
    # Malformed string should be treated as 0.0
    assert is_above_floor("not_a_number", 50_000.0) is False


def test_critical_event_skips_score_but_not_value_gate() -> None:
    gate = EventGate(min_score_threshold=0.65)
    for event_type in CRITICAL_EVENT_TYPES:
        assert not gate.should_investigate(_event(event_type=event_type, score=0.1, value_usd=1.0))
        assert gate.should_investigate(_event(event_type=event_type, score=0.1, value_usd=100_000.0))


def test_min_whale_threshold_constant() -> None:
    assert MIN_WHALE_THRESHOLD_USD == 50_000.0


async def test_process_gate_prices_amount_and_passes_whale() -> None:
    # 1,000,000 SHIB at $0.00003 → $30 is below the floor; 3,000,000,000 at
    # $0.00003 → $90,000 clears it. The true USD value comes from amount × price.
    event = _event(score=0.9)
    event.raw_json["data"] = hex(int(3_000_000_000 * 10**18))  # 3B SHIB
    event.raw_json["address"] = "0x" + "c" * 40
    assert await process_and_gate_candidate(event, _FakeOracle(0.00003))
    assert event.raw_json["value_usd"] == pytest.approx(90_000.0)


async def test_process_gate_drops_when_price_unknown() -> None:
    # Unknown token (price 0.0) → value 0 → skipped, never reaches LLM.
    event = _event(score=0.9)
    event.raw_json["data"] = hex(int(1_000_000 * 10**18))
    assert not await process_and_gate_candidate(event, _FakeOracle(0.0))
    assert event.status == "skipped"
    assert event.score == 0.0


async def test_process_gate_uses_historical_price_at_event_time() -> None:
    # 3B SHIB priced at an old event timestamp ($0.00002 then) → $60k passes the
    # floor via the historical path, not today's current price.
    event = _event(score=0.9)
    event.raw_json["data"] = hex(int(3_000_000_000 * 10**18))
    assert await process_and_gate_candidate(event, _FakeOracle(price=0.0, historical=0.00002), timestamp=1700000000)
    assert event.raw_json["value_usd"] == pytest.approx(60_000.0)
