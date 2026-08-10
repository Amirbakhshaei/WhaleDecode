from whaledecode.domain.entities.candidate_event import CandidateEvent
from whaledecode.domain.services.event_gate import (
    CRITICAL_EVENT_TYPES,
    MIN_WHALE_THRESHOLD_USD,
    EventGate,
)
from whaledecode.domain.value_objects.hash import Hash

TX_HASH = "0x" + "b" * 64


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


def test_critical_event_skips_score_but_not_value_gate() -> None:
    gate = EventGate(min_score_threshold=0.65)
    for event_type in CRITICAL_EVENT_TYPES:
        assert not gate.should_investigate(_event(event_type=event_type, score=0.1, value_usd=1.0))
        assert gate.should_investigate(_event(event_type=event_type, score=0.1, value_usd=100_000.0))


def test_min_whale_threshold_constant() -> None:
    assert MIN_WHALE_THRESHOLD_USD == 50_000.0
