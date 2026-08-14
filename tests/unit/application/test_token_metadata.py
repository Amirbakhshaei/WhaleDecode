"""Unit tests for TokenMetadataService (offline — no network / no RPC)."""
from __future__ import annotations

import asyncio
import json

from whaledecode.label_ingestion.token_metadata import TokenMetadataService

SAMPLE = {
    "tokens": [
        {"chainId": 1, "address": "0xdac17f958d2ee523a2206206994597c13d831ec7", "name": "Tether USD", "symbol": "USDT", "decimals": 6},
        {"chainId": 56, "address": "0x55d398326f99059ff775485246999027b31979539", "name": "BUSD", "symbol": "BUSD", "decimals": 18},  # BSC unsupported
        {"chainId": 42161, "address": "0xzzz", "name": "bad", "symbol": "X", "decimals": 0},  # invalid addr
    ]
}


def test_parse_token_list_filters_and_checksums() -> None:
    svc = TokenMetadataService()
    labels = svc.parse_token_list(json.dumps(SAMPLE), source="uniswap")
    assert len(labels) == 1  # BSC(56) dropped, invalid address dropped
    lbl = labels[0]
    assert lbl.chain_id == 1
    assert lbl.address == "0xdAC17F958D2ee523a2206206994597C13D831ec7"  # EIP-55
    assert lbl.category == "Token"
    assert svc.get(lbl.address, 1) is not None


def test_resolve_returns_cached() -> None:
    svc = TokenMetadataService()
    svc.parse_token_list(json.dumps(SAMPLE), source="x")
    lbl = asyncio.run(svc.resolve("0xdac17f958d2ee523a2206206994597c13d831ec7", 1))
    assert lbl is not None and lbl.chain_id == 1


def test_resolve_graceful_without_rpc() -> None:
    svc = TokenMetadataService()  # no rpc_urls configured
    lbl = asyncio.run(svc.resolve("0x0000000000000000000000000000000000000001", 1))
    assert lbl is None  # missing + no RPC -> None, never raises


class _FakeResp:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        pass


class _FakeClient:
    def __init__(self, payload: str) -> None:
        self._payload = payload

    async def get(self, url: str) -> _FakeResp:
        return _FakeResp(self._payload)


def test_load_lists_union() -> None:
    svc = TokenMetadataService()
    labels = asyncio.run(svc.load_lists(client=_FakeClient(json.dumps(SAMPLE))))
    assert any(label.address == "0xdAC17F958D2ee523a2206206994597C13D831ec7" for label in labels)
