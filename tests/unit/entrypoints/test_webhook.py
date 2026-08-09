"""Unit tests for the Alchemy webhook entrypoint (FastAPI version)."""
import hashlib
import hmac

from fastapi.testclient import TestClient

from whaledecode.domain.entities.candidate_event import CandidateEvent
from whaledecode.domain.entities.curated_wallet import CuratedWallet
from whaledecode.domain.value_objects.chain import Chain
from whaledecode.entrypoints.webhook import (
    _NETWORK_TO_CHAIN,
    _activity_candidate,
    _score_candidate,
    verify_alchemy_signature,
    app,
)


def test_verify_alchemy_signature_valid():
    key = "test_signing_key"
    body = b'{"test": "payload"}'
    sig = hmac.new(key.encode(), body, hashlib.sha256).hexdigest()
    assert verify_alchemy_signature(body, sig, [key]) is True


def test_verify_alchemy_signature_invalid():
    key = "test_signing_key"
    body = b'{"test": "payload"}'
    assert verify_alchemy_signature(body, "wrong_sig", [key]) is False


def test_verify_alchemy_signature_missing():
    assert verify_alchemy_signature(b"body", None, ["key"]) is False
    assert verify_alchemy_signature(b"body", "", ["key"]) is False


def test_verify_alchemy_signature_multi_key():
    key1 = "key1"
    key2 = "key2"
    body = b'{"test": "payload"}'
    sig2 = hmac.new(key2.encode(), body, hashlib.sha256).hexdigest()
    assert verify_alchemy_signature(body, sig2, [key1, key2]) is True


def test_network_mapping():
    assert _NETWORK_TO_CHAIN["ETH_MAINNET"] is Chain.ETH
    assert _NETWORK_TO_CHAIN["BASE_MAINNET"] is Chain.BASE
    assert _NETWORK_TO_CHAIN["ARB_MAINNET"] is Chain.ARB
    assert _NETWORK_TO_CHAIN.get("SOLANA_MAINNET") is None


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


def test_fastapi_app_has_routes():
    """Verify FastAPI app has the webhook and health routes."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    # Webhook endpoint exists (returns 401 without signature, not 404)
    response = client.post("/webhook/alchemy", json={})
    assert response.status_code == 401  # signature verification fails