"""Resilient chain provider: wraps ResilientRPCManager with the ChainProviderPort interface.

Replaces HttpRpcProvider (1 paid URL/chain) with ResilientRPCManager
(N free URLs + circuit breaker + rate limiter) as the default RPC system.

Token metadata caching and Multicall3 batching are carried over from
HttpRpcProvider — they are transport-agnostic optimisations that work
on top of any JSON-RPC backend.
"""
from __future__ import annotations

from typing import Any

import eth_abi
import structlog
from cachetools import TTLCache
from eth_utils import to_checksum_address

from whaledecode.adapters.chain.providers.http_rpc import (
    ERC20_BALANCE_OF_SELECTOR,
    ERC20_METADATA_ABI,
    MULTICALL3_ADDRESS,
    MULTICALL3_AGGREGATE3_SELECTOR,
    TOKEN_METADATA_CACHE_SIZE,
    TOKEN_METADATA_CACHE_TTL_SECONDS,
)
from whaledecode.domain.ports.chain_provider import ChainProviderPort
from whaledecode.pools.rpc.manager import ResilientRPCManager

log = structlog.get_logger()

# Chain code (as used by ChainProviderPort callers) → ResilientRPCManager chain name.
_CHAIN_MAP: dict[str, str] = {
    "ETH": "ethereum",
    "ETHEREUM": "ethereum",
    "ARB": "arbitrum",
    "ARBITRUM": "arbitrum",
    "BASE": "base",
}

_TOKEN_METADATA_CACHE: TTLCache[tuple[str, str], dict[str, Any]] = TTLCache(
    maxsize=TOKEN_METADATA_CACHE_SIZE, ttl=TOKEN_METADATA_CACHE_TTL_SECONDS
)


class ResilientChainProvider(ChainProviderPort):
    """ChainProviderPort backed by ResilientRPCManager (free RPCs + circuit breaker)."""

    def __init__(self, rpc: ResilientRPCManager) -> None:
        self._rpc = rpc

    def _chain_name(self, chain: str) -> str:
        name = _CHAIN_MAP.get(chain.upper())
        if name is None:
            raise ValueError(f"Unsupported chain: {chain}. Supported: {list(_CHAIN_MAP)}")
        return name

    async def _call(self, method: str, params: list[Any] | None, chain: str) -> Any:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}
        return await self._rpc.execute(self._chain_name(chain), payload)

    async def get_logs(
        self,
        chain: str,
        addresses: list[str],
        from_block: int,
        to_block: int,
        topics: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
        }
        if addresses:
            params["address"] = addresses
        if topics:
            params["topics"] = topics
        result = await self._call("eth_getLogs", [params], chain)
        return result if isinstance(result, list) else []

    async def get_block_number(self, chain: str) -> int:
        result = await self._call("eth_blockNumber", [], chain)
        return int(result, 16) if result else 0

    async def get_balance(self, chain: str, address: str) -> str:
        result = await self._call("eth_getBalance", [address, "latest"], chain)
        return result if isinstance(result, str) else "0x0"

    async def get_transaction_count(self, chain: str, address: str) -> int:
        result = await self._call("eth_getTransactionCount", [address, "latest"], chain)
        return int(result, 16) if isinstance(result, str) and result else 0

    async def get_token_metadata(self, chain: str, address: str) -> dict[str, Any]:
        cache_key = (chain.upper(), address.lower())
        cached = _TOKEN_METADATA_CACHE.get(cache_key)
        if cached is not None:
            return cached

        async def _eth_call(data_hex: str) -> str:
            params = [{"to": address, "data": data_hex}, "latest"]
            result = await self._call("eth_call", params, chain)
            return result or "0x"

        name_hex = await _eth_call(ERC20_METADATA_ABI["name"])
        symbol_hex = await _eth_call(ERC20_METADATA_ABI["symbol"])
        decimals_hex = await _eth_call(ERC20_METADATA_ABI["decimals"])

        def _decode_hex_string(hex_str: str) -> str:
            try:
                raw = bytes.fromhex(hex_str[2:])
                if len(raw) >= 64:
                    offset = int.from_bytes(raw[:32], "big")
                    length = int.from_bytes(raw[offset : offset + 32], "big")
                    start = offset + 32
                    return raw[start : start + length].decode("utf-8", errors="replace")
                return raw.decode("utf-8", errors="replace").strip("\x00")
            except (ValueError, IndexError):
                return ""

        metadata = {
            "name": _decode_hex_string(name_hex) or "Unknown",
            "symbol": _decode_hex_string(symbol_hex) or "???",
            "decimals": int(decimals_hex, 16) if decimals_hex and decimals_hex != "0x" else 18,
            "address": address,
        }
        _TOKEN_METADATA_CACHE[cache_key] = metadata
        return metadata

    async def get_token_balances(self, chain: str, address: str, token_addresses: list[str]) -> dict[str, int]:
        if not token_addresses:
            return {}
        calls = [
            (
                to_checksum_address(token),
                True,
                ERC20_BALANCE_OF_SELECTOR + to_checksum_address(address).lower()[2:].zfill(64),
            )
            for token in token_addresses
        ]
        data_hex = MULTICALL3_AGGREGATE3_SELECTOR + eth_abi.encode(["(address,bool,bytes)[]"], [calls]).hex()
        result = await self._call(
            "eth_call",
            [{"to": MULTICALL3_ADDRESS, "data": data_hex}, "latest"],
            chain,
        )
        if not isinstance(result, str) or not result.startswith("0x"):
            return {}
        try:
            decoded = eth_abi.decode(["(bool,bytes)[]"], bytes.fromhex(result[2:]))
        except ValueError:
            return {}
        balances: dict[str, int] = {}
        for token, (success, ret) in zip(token_addresses, decoded):
            if success and len(ret) >= 32:
                balances[token.lower()] = int.from_bytes(ret[:32], "big")
        return balances

    async def trace_call(self, chain: str, tx_hash: str) -> dict[str, Any]:
        result = await self._call("trace_transaction", [tx_hash], chain)
        if isinstance(result, list):
            return result[0] if result else {}
        return result if isinstance(result, dict) else {}

    async def close(self) -> None:
        await self._rpc.aclose()
