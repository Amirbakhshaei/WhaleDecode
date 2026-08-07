from whaledecode.domain.policies.sentinel import SUPER_WHALE_TRANSFER_THRESHOLD_USD, SentinelEngine


def _transfer(usd: float, wallet_id: int | None = 10, tx_hash: str | None = "0xtx") -> dict:
    event = {
        "wallet_id": wallet_id,
        "tx_hash": tx_hash,
        "event_type": "TRANSFER",
        "value_usd": usd,
    }
    return event


def test_whale_transfer_alone_below_50_gate() -> None:
    score = SentinelEngine().score(_transfer(200_000))
    assert score == 40.0
    assert score < 50.0


def test_accumulation_burst_breaches_50() -> None:
    engine = SentinelEngine()
    event = _transfer(200_000, wallet_id=1)
    recent = [{"wallet_id": 1, "tx_hash": f"0xa{i}"} for i in range(2)]
    score = engine.score(event, recent_events=recent)
    assert score >= 50.0


def test_super_whale_single_transfer_breaches_50() -> None:
    score = SentinelEngine().score(_transfer(SUPER_WHALE_TRANSFER_THRESHOLD_USD))
    assert score >= 50.0


def test_multi_wallet_confluence_breaches_50() -> None:
    engine = SentinelEngine()
    event = _transfer(200_000, wallet_id=1, tx_hash="0xshared")
    recent = [
        {"wallet_id": 1, "tx_hash": "0xshared"},
        {"wallet_id": 2, "tx_hash": "0xshared"},
    ]
    score = engine.score(event, recent_events=recent)
    assert score >= 50.0
