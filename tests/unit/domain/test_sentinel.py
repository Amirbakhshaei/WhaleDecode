from typing import Any

from whaledecode.domain.policies.sentinel import (
    CURATED_WALLET_BONUS,
    SUPER_WHALE_TRANSFER_THRESHOLD_USD,
    SentinelEngine,
    score_base_value,
)


def _transfer(usd: float, wallet_id: int | None = 10, tx_hash: str | None = "0xtx") -> dict[str, Any]:
    event = {
        "wallet_id": wallet_id,
        "tx_hash": tx_hash,
        "event_type": "TRANSFER",
        "value_usd": usd,
    }
    return event


def test_untracked_lone_whale_transfer_stays_below_50() -> None:
    """A lone 200k transfer from a non-curated wallet scores 35, below the gate."""
    score = SentinelEngine().score(_transfer(200_000))
    assert score == 35.0
    assert score < 50.0


def test_curated_bonus_lifts_million_transfer_past_50() -> None:
    """A 1M transfer (45) plus curated bonus (10) crosses the gate."""
    score = SentinelEngine().score(
        _transfer(1_000_000, wallet_id=1), curated_wallet_ids={1}
    )
    assert score == 45.0 + CURATED_WALLET_BONUS
    assert score >= 50.0


def test_curated_bonus_does_not_lift_lone_100k_transfer() -> None:
    """A 100k transfer (35) plus curated bonus (10) stays below the gate."""
    score = SentinelEngine().score(
        _transfer(100_000, wallet_id=1), curated_wallet_ids={1}
    )
    assert score == 35.0 + CURATED_WALLET_BONUS
    assert score < 50.0


def test_accumulation_burst_breaches_50() -> None:
    engine = SentinelEngine()
    event = _transfer(1_000_000, wallet_id=1)
    recent = [{"wallet_id": 1, "tx_hash": f"0xa{i}"} for i in range(3)]
    score = engine.score(event, recent_events=recent)
    assert score >= 50.0


def test_super_whale_single_transfer_breaches_50() -> None:
    score = SentinelEngine().score(_transfer(SUPER_WHALE_TRANSFER_THRESHOLD_USD))
    assert score >= 50.0


def test_ten_million_transfer_is_instant_pass() -> None:
    score = SentinelEngine().score(_transfer(10_000_000))
    assert score >= 50.0


def test_multi_wallet_confluence_breaches_50() -> None:
    engine = SentinelEngine()
    event = _transfer(1_000_000, wallet_id=1, tx_hash="0xshared")
    recent = [
        {"wallet_id": 1, "tx_hash": "0xshared"},
        {"wallet_id": 2, "tx_hash": "0xshared"},
    ]
    score = engine.score(event, recent_events=recent)
    assert score >= 50.0


def test_score_base_value_tiers() -> None:
    assert score_base_value(50_000_000) == 60.0
    assert score_base_value(10_000_000) == 50.0
    assert score_base_value(1_000_000) == 45.0
    assert score_base_value(100_000) == 35.0
    assert score_base_value(99_999) == 0.0
