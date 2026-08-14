"""Token metadata ingestion: Uniswap/CoinGecko token lists + on-chain RPC fallback.

Token identities (address -> name/symbol/decimals) are a first-class label source.
We load the canonical Uniswap and CoinGecko token lists (Uniswap token-list schema)
into a cache, then expose a per-address ``resolve`` that falls back to an on-chain
Multicall3 batch of ``symbol()`` / ``decimals()`` / ``name()`` for any address not
present in the lists.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from web3 import AsyncHTTPProvider, AsyncWeb3, Web3
from whaledecode.label_ingestion.config import MULTICALL3_ADDRESS, TOKEN_LIST_URLS
from whaledecode.label_ingestion.normalizer import (
    SUPPORTED_CHAIN_IDS,
    AddressLabel,
    is_valid_address,
)

log = logging.getLogger(__name__)

ERC20_ABI: list[dict[str, Any]] = [
    {"name": "symbol", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"name": "", "type": "string"}]},
    {"name": "decimals", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"name": "", "type": "uint8"}]},
    {"name": "name", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"name": "", "type": "string"}]},
]
MULTICALL3_ABI: list[dict[str, Any]] = [
    {
        "name": "aggregate",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {
                "name": "calls",
                "type": "tuple[]",
                "components": [
                    {"name": "target", "type": "address"},
                    {"name": "callData", "type": "bytes"},
                ],
            }
        ],
        "outputs": [
            {"name": "blockNumber", "type": "uint256"},
            {"name": "returnData", "type": "bytes[]"},
        ],
    }
]


class TokenMetadataService:
    """In-memory cache of token labels backed by the public token lists."""

    def __init__(self, rpc_urls: dict[int, str] | None = None) -> None:
        # chain_id -> checksum_address -> AddressLabel
        self._cache: dict[tuple[str, int], AddressLabel] = {}
        self._rpc_urls = {int(k): v for k, v in (rpc_urls or {}).items() if v}

    # -- bulk load ---------------------------------------------------------

    def parse_token_list(self, text: str, source: str = "") -> list[AddressLabel]:
        """Parse a Uniswap token-list JSON document into AddressLabel rows."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            log.warning("token_list_parse_error", extra={"source": source, "error": str(exc)})
            return []
        out: list[AddressLabel] = []
        for tok in data.get("tokens", []):
            addr = tok.get("address")
            if not is_valid_address(addr):
                continue
            chain_id = tok.get("chainId")
            if chain_id not in SUPPORTED_CHAIN_IDS:
                continue  # only the chains we explicitly support (1/42161/8453/0)
            name = tok.get("name") or tok.get("symbol") or addr
            label = AddressLabel(
                address=addr,
                chain_id=int(chain_id),
                name_tag=name,
                entity=name,
                category="Token",
                source=source or "token-list",
                confidence_score=0.9,
            )
            out.append(label)
            self._cache[(label.address, label.chain_id)] = label
        return out

    async def load_lists(self, client: httpx.AsyncClient | None = None) -> list[AddressLabel]:
        """Fetch every URL in TOKEN_LIST_URLS and return the union of token labels."""
        owned = client is None
        if owned:
            client = httpx.AsyncClient(timeout=30.0, headers={"Accept": "application/json"})
        labels: list[AddressLabel] = []
        try:
            for url in TOKEN_LIST_URLS:
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    labels.extend(self.parse_token_list(resp.text, source=url))
                except Exception as exc:  # noqa: BLE001 - one list failing must not abort the rest
                    log.warning("token_list_fetch_failed", extra={"url": url, "error": str(exc)})
        finally:
            if owned:
                await client.aclose()
        return labels

    # -- per-address resolution (runtime) ----------------------------------

    def get(self, address: str, chain_id: int) -> AddressLabel | None:
        try:  # normalize case so lookups are case-insensitive
            key = (Web3.to_checksum_address(address), chain_id)
        except Exception:  # noqa: BLE001 - invalid address -> not in cache
            return None
        return self._cache.get(key)

    async def resolve(self, address: str, chain_id: int) -> AddressLabel | None:
        """Return the cached label, or fetch on-chain via Multicall3 if missing.

        Returns ``None`` when the token isn't in the lists and no RPC is configured
        or the on-chain call fails — never raises."""
        try:
            address = Web3.to_checksum_address(address)
        except Exception:  # noqa: BLE001 - malformed address -> nothing to resolve
            return None
        cached = self.get(address, chain_id)
        if cached is not None:
            return cached
        return await self._rpc_resolve(address, chain_id)

    async def _rpc_resolve(self, address: str, chain_id: int) -> AddressLabel | None:
        rpc = self._rpc_urls.get(chain_id)
        if not rpc:
            return None
        try:
            w3 = AsyncWeb3(AsyncHTTPProvider(rpc))
            token = w3.eth.contract(address=w3.to_checksum_address(address), abi=ERC20_ABI)
            mc = w3.eth.contract(
                address=w3.to_checksum_address(MULTICALL3_ADDRESS), abi=MULTICALL3_ABI
            )
            calls = [
                (token.address, token.functions.symbol()._encode_transaction_data()),
                (token.address, token.functions.decimals()._encode_transaction_data()),
                (token.address, token.functions.name()._encode_transaction_data()),
            ]
            _, return_data = await mc.functions.aggregate(calls).call()
            symbol = w3.codec.decode([{"type": "string"}], return_data[0])[0] or ""
            decimals = w3.codec.decode([{"type": "uint8"}], return_data[1])[0]
            name = w3.codec.decode([{"type": "string"}], return_data[2])[0] or symbol or address
            label = AddressLabel(
                address=token.address,
                chain_id=chain_id,
                name_tag=name,
                entity=name,
                category="Token",
                source=f"rpc:{chain_id}",
                confidence_score=0.7,
            )
            self._cache[(token.address, chain_id)] = label
            log.info("token_rpc_resolved", extra={"address": token.address, "chain_id": chain_id, "name": name, "decimals": decimals})
            return label
        except Exception as exc:  # noqa: BLE001 - RPC is a best-effort fallback
            log.warning("token_rpc_resolve_failed", extra={"address": address, "chain_id": chain_id, "error": str(exc)})
            return None
