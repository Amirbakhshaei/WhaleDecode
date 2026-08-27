"""Unit tests for the webhook entrypoint's parsing helpers.

The HTTP ingestion route itself is deprecated (replaced by the Targeted
Failover Poller); these cover the pure parsing/scoring logic that the
migration still references.
"""
import asyncio

from fastapi.testclient import TestClient
from whaledecode.domain.entities.candidate_event import CandidateEvent
from whaledecode.domain.entities.curated_wallet import CuratedWallet
from whaledecode.domain.value_objects.chain import Chain
from whaledecode.entrypoints import webhook
from whaledecode.entrypoints.webhook import (
    _activity_candidate,
    _below_chain_floor,
    _build_candidate_data,
    _clears_chain_floor,
    _is_ignorable_activity,
    _score_candidate,
    app,
)


def test_activity_candidate_token_transfer():
    from whaledecode.adapters.chain.normalizer import TRANSFER_EVENT_SIGNATURE, pad_address_to_topic

    activity = {
        "blockNum": "0xdf34a3",
        "hash": "0x" + "a" * 64,
        "fromAddress": "0x503828976d22510aad0201ac7ec88293211d23da",
        "toAddress": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18",
        "value": 1_500_000.0,
        "asset": "USDC",
        "category": "token",
        "log": {
            "address": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
            "topics": [
                TRANSFER_EVENT_SIGNATURE,
                pad_address_to_topic("0x503828976d22510aad0201ac7ec88293211d23da"),
                pad_address_to_topic("0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18"),
            ],
            "logIndex": "0x5",
            "blockNumber": "0xdf34a3",
            "transactionHash": "0x" + "a" * 64,
        },
    }
    wallet = CuratedWallet(
        id=1,
        address="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18",
        chain=Chain.ETH,
        label="Test Whale",
    )
    candidate = _activity_candidate(activity, Chain.ETH, wallet)

    assert candidate.wallet_id == 1
    assert candidate.chain == "Ethereum"
    assert candidate.tx_hash == "0x" + "a" * 64
    assert candidate.log_index == 5
    assert candidate.block_number == 0xDF34A3
    assert candidate.event_type == "TRANSFER"
    assert candidate.raw_json["value_usd"] == 1_500_000.0
    assert candidate.dedupe_key == "1:0x" + "a" * 64 + ":5"


def test_activity_candidate_external_eth():
    activity = {
        "blockNum": "0xdf34a3",
        "hash": "0x" + "b" * 64,
        "fromAddress": "0x503828976d22510aad0201ac7ec88293211d23da",
        "toAddress": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18",
        "value": 50.0,
        "asset": "ETH",
        "category": "external",
        "log": {},
    }
    wallet = CuratedWallet(
        id=2,
        address="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18",
        chain=Chain.ETH,
        label="Test Whale",
    )
    candidate = _activity_candidate(activity, Chain.ETH, wallet)
    assert candidate.event_type == "TRANSFER"
    assert candidate.raw_json["value_usd"] == 50.0
    assert candidate.dedupe_key == "2:0x" + "b" * 64 + ":0"


def test_score_candidate_whale_transfer():
    candidate = CandidateEvent(
        wallet_id=3,
        chain="Ethereum",
        tx_hash="0x" + "c" * 64,
        log_index=0,
        block_number=100,
        event_type="TRANSFER",
        raw_json={"value_usd": 2_000_000.0},
        score=0.0,
        dedupe_key="3:0x" + "c" * 64 + ":0",
    )
    score = _score_candidate(candidate)
    assert score >= 50.0


def test_build_candidate_data_scores_whale_transfer():
    """Ingested webhook events must carry a real sentinel score, not 0.0."""
    from whaledecode.adapters.chain.normalizer import TRANSFER_EVENT_SIGNATURE, pad_address_to_topic
    from whaledecode.entrypoints.webhook import _build_candidate_data

    activity = {
        "blockNum": "0xdf34a3",
        "hash": "0x" + "d" * 64,
        "fromAddress": "0x503828976d22510aad0201ac7ec88293211d23da",
        "toAddress": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18",
        "value": 1_000_000.0,
        "asset": "USDC",
        "category": "token",
        "log": {
            "address": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
            "topics": [
                TRANSFER_EVENT_SIGNATURE,
                pad_address_to_topic("0x503828976d22510aad0201ac7ec88293211d23da"),
                pad_address_to_topic("0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18"),
            ],
            "logIndex": "0x5",
            "blockNumber": "0xdf34a3",
            "transactionHash": "0x" + "d" * 64,
        },
    }
    wallet = CuratedWallet(
        id=1,
        address="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18",
        chain=Chain.ETH,
        label="Test Whale",
    )
    data = _build_candidate_data(activity, Chain.ETH, wallet)
    assert data["score"] >= 50.0
    assert data["score"] == _score_candidate(_activity_candidate(activity, Chain.ETH, wallet))


def test_build_candidate_data_scores_low_value_transfer_low():
    """A sub-whale transfer (curated-bonus only) stays well below the whale gate."""
    from whaledecode.entrypoints.webhook import _build_candidate_data

    activity = {
        "blockNum": "0xdf34a3",
        "hash": "0x" + "e" * 64,
        "fromAddress": "0x503828976d22510aad0201ac7ec88293211d23da",
        "toAddress": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18",
        "value": 10.0,
        "asset": "USDC",
        "category": "token",
        "log": {},
    }
    wallet = CuratedWallet(
        id=1,
        address="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18",
        chain=Chain.ETH,
        label="Test Whale",
    )
    data = _build_candidate_data(activity, Chain.ETH, wallet)
    assert data["score"] < 50.0


def test_fastapi_app_has_routes():
    """Verify FastAPI app serves /health (ingestion route deprecated)."""
    client = TestClient(app)
    response = client.get("/health")
    # Health is truthful: 200 when ready, 503 when bot not yet running or degraded.
    # In TestClient without lifespan, bot_not_running is expected (degraded 503).
    assert response.status_code in (200, 503)
    assert response.json()["status"] in ("ok", "degraded")

    # The Alchemy ingestion route is a deprecation stub: acks 200 (stops
    # vendor retry storms) but ingests nothing.
    response = client.post("/webhook/alchemy", json={})
    assert response.status_code == 200
    assert response.json()["status"] == "deprecated"


def test_ignorable_activity_zero_value_external():
    """Zero-value native transfers / empty contract calls are rejected pre-insert."""
    assert _is_ignorable_activity(
        {"category": "external", "value": "0", "rawContract": {"rawValue": "0x0"}}
    )
    assert _is_ignorable_activity({"category": "external", "value": 0.0, "rawContract": {"rawValue": None}})
    assert _is_ignorable_activity({"category": "external", "rawContract": {"rawValue": "0x"}})


def test_non_ignorable_activities_pass_through():
    """Non-zero native, and all token categories, are never gated here."""
    assert not _is_ignorable_activity(
        {"category": "external", "value": "1.5", "rawContract": {"rawValue": "0x15af1d78b58c40000"}}
    )
    assert not _is_ignorable_activity({"category": "erc20", "value": "0x0", "rawContract": {"rawValue": "0x0"}})
    assert not _is_ignorable_activity({"category": "external", "value": "0.5"})


def test_below_chain_floor_gates_by_chain_threshold():
    """Sub-floor USD noise is dropped in memory before any DB session."""
    assert _below_chain_floor({"value": 100.0}, Chain.ETH) is True
    assert _below_chain_floor({"value": 260_000.0}, Chain.ETH) is False
    assert _below_chain_floor({"value": 100.0}, Chain.ARB) is True
    assert _below_chain_floor({"value": 60_000.0}, Chain.ARB) is False
    assert _below_chain_floor({"value": 30_000.0}, Chain.BASE) is False


def test_below_chain_floor_ignores_unpriced_activities():
    """Hex/absent USD values (0.0) are never floor-gated — re-priced downstream."""
    assert _below_chain_floor({"value": "0x989680"}, Chain.ETH) is False
    assert _below_chain_floor({}, Chain.ETH) is False


def test_build_candidate_data_scales_token_amount_by_contract_decimals():
    """6-decimal token (USDT/USDC) raw hex must not be treated as 18-decimal."""
    activity = {
        "blockNum": "0xdf34a3",
        "hash": "0x" + "f" * 64,
        "fromAddress": "0x503828976d22510aad0201ac7ec88293211d23da",
        "toAddress": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18",
        "value": "0x989680",  # 10,000,000 raw units
        "asset": "USDT",
        "category": "erc20",
        "rawContract": {"address": "0xdac17f958d2ee523a2206206994597c13d831ec7", "rawValue": "0x989680", "decimal": 6},
        "log": {},
    }
    wallet = CuratedWallet(
        id=1,
        address="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18",
        chain=Chain.ETH,
        label="Test Whale",
    )
    data = _build_candidate_data(activity, Chain.ETH, wallet)
    # 10,000,000 raw / 10^6 = 10.0 USDT — NOT 10^12× larger from an 18-decimal read.
    assert data["raw_json"]["token_amount"] == 10.0
    assert data["raw_json"]["decimals"] == 6
    # hex token value is not a USD figure → conservative 0.0 placeholder.
    assert data["raw_json"]["value_usd"] == 0.0


def test_build_candidate_data_defaults_to_18_decimals():
    """Absent decimals hint → ERC-20 default of 18."""
    activity = {
        "blockNum": "0xdf34a3",
        "hash": "0x" + "a1" * 32,
        "fromAddress": "0x503828976d22510aad0201ac7ec88293211d23da",
        "toAddress": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18",
        "value": 1000.0,
        "asset": "WETH",
        "category": "external",
        "log": {},
    }
    wallet = CuratedWallet(
        id=1,
        address="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18",
        chain=Chain.ETH,
        label="Test Whale",
    )
    data = _build_candidate_data(activity, Chain.ETH, wallet)
    assert data["raw_json"]["decimals"] == 18
    assert data["raw_json"]["value_usd"] == 1000.0


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


def test_clears_chain_floor_prices_via_oracle(monkeypatch):
    """Ingestion gate prices the move and enforces the chain's per-chain floor."""
    wallet = CuratedWallet(id=1, address="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18", chain=Chain.ETH, label="Test Whale")
    data = _build_candidate_data(_erc20_activity(1000.0), Chain.ETH, wallet)
    monkeypatch.setattr(webhook, "_price_oracle", _FakeOracle(600.0))

    assert asyncio.run(_clears_chain_floor(data)) is True
    assert data["raw_json"]["value_usd"] == 600_000.0


def test_clears_chain_floor_drops_below_threshold(monkeypatch):
    """Sub-floor move is rejected and never persists — priced value still recorded."""
    wallet = CuratedWallet(id=1, address="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18", chain=Chain.ETH, label="Test Whale")
    data = _build_candidate_data(_erc20_activity(1000.0), Chain.ETH, wallet)
    monkeypatch.setattr(webhook, "_price_oracle", _FakeOracle(100.0))

    assert asyncio.run(_clears_chain_floor(data)) is False
    assert data["raw_json"]["value_usd"] == 100_000.0


def test_clears_chain_floor_uses_per_chain_floor(monkeypatch):
    """BASE's $30k floor governs ingestion, not the flat $50k downstream gate."""
    wallet = CuratedWallet(id=1, address="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18", chain=Chain.BASE, label="Test Whale")
    data = _build_candidate_data(_erc20_activity(1000.0), Chain.BASE, wallet)
    monkeypatch.setattr(webhook, "_price_oracle", _FakeOracle(50.0))

    assert asyncio.run(_clears_chain_floor(data)) is True
    assert data["raw_json"]["value_usd"] == 50_000.0
