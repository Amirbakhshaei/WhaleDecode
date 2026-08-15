import asyncio
import time
from typing import Any

import eth_abi
import httpx
import structlog
from aiolimiter import AsyncLimiter
from eth_utils import to_checksum_address
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential
from whaledecode.domain.ports.chain_provider import ChainProviderPort

DEFAULT_HEADERS = {
    "User-Agent": "WhaleDecodeBot/1.0",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# Hard ceiling on outbound RPC traffic: 15 requests per 60 seconds across the
# whole process. Every worker shares this one limiter, so bursts are impossible.
RATE_LIMIT_MAX_RATE = 15
RATE_LIMIT_PERIOD_SECONDS = 60
RATE_LIMIT_WAIT_SECONDS = 5

CHAIN_ALIASES: dict[str, str] = {
    "ETH": "ETH",
    "ETHEREUM": "ETH",
    "ARB": "ARB",
    "ARBITRUM": "ARB",
    "BASE": "BASE",
}

ERC20_METADATA_ABI = {
    "name": "0x06fdde03",
    "symbol": "0x95d89b41",
    "decimals": "0x313ce567",
}

# Multicall3 (same address on ETH/ARB/BASE) batches N token balanceOf calls into
# ONE eth_call, so a portfolio probe is a single RPC request — keeps us under
# the shared rate limiter instead of N sequential calls.
MULTICALL3_ADDRESS = "0xcA11bde05977b3631167028862bE2a173976CA11"
MULTICALL3_AGGREGATE3_SELECTOR = "0x82ad56cb"
ERC20_BALANCE_OF_SELECTOR = "0x70a08231"


class RateLimitError(Exception):
    """Raised when the shared rate limiter cannot be acquired in time."""


class HttpRpcProvider(ChainProviderPort):
    def __init__(self, chain_urls: dict[str, str], timeout: int = 30) -> None:
        self._urls = {chain.upper(): url for chain, url in chain_urls.items()}
        self._client = httpx.AsyncClient(timeout=timeout, headers=DEFAULT_HEADERS)
        self._timeout = timeout
        self._limiter = AsyncLimiter(max_rate=RATE_LIMIT_MAX_RATE, time_period=RATE_LIMIT_PERIOD_SECONDS)
        self._rate_limit_wait = RATE_LIMIT_WAIT_SECONDS
        self._log = structlog.get_logger()

    def _url_for_chain(self, chain: str) -> str:
        code = CHAIN_ALIASES.get(chain.upper(), chain.upper())
        url = self._urls.get(code)
        if not url:
            raise ValueError(f"Unsupported chain: {chain}. Supported: {list(self._urls)}")
        return url

    def _raise_with_body(self, chain: str, method: str, resp: httpx.Response, reason: str) -> None:
        body = resp.text[:500]
        self._log.error(
            "rpc_invalid_response",
            chain=chain,
            method=method,
            status=resp.status_code,
            reason=reason,
            body=body,
        )
        raise ValueError(f"RPC {reason} from {chain} (status {resp.status_code}): {body}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        retry=retry_if_not_exception_type(RateLimitError),
    )
    async def rpc_call(self, method: str, params: list[Any] | None = None, chain: str = "ETH") -> Any:
        url = self._url_for_chain(chain)
        payload = {"jsonrpc": "2.0", "method": method, "params": params or [], "id": int(time.time())}
        try:
            await asyncio.wait_for(self._limiter.acquire(), timeout=self._rate_limit_wait)
        except TimeoutError as e:
            self._log.warning("rpc_rate_limited", chain=chain, method=method)
            raise RateLimitError(f"Rate limit reached on {chain} for {method}") from e
        resp = await self._client.post(url, json=payload)
        if resp.status_code != 200:
            self._raise_with_body(chain, method, resp, "non-200 response")
        try:
            data = resp.json()
        except ValueError:
            self._raise_with_body(chain, method, resp, "non-JSON response")
        if "error" in data:
            raise ValueError(f"RPC error on {chain}: {data['error']}")
        return data.get("result")

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
        # Topic-scoped search (ERC-20 Transfer) needs no address filter; the
        # wallet appears inside the topic array, not as a log emitter.
        if addresses:
            params["address"] = addresses
        if topics:
            params["topics"] = topics
        result = await self.rpc_call("eth_getLogs", [params], chain=chain)
        return result if isinstance(result, list) else []

    async def get_block_number(self, chain: str) -> int:
        result = await self.rpc_call("eth_blockNumber", chain=chain)
        return int(result, 16) if result else 0

    async def get_balance(self, chain: str, address: str) -> str:
        result = await self.rpc_call("eth_getBalance", [address, "latest"], chain=chain)
        return result if isinstance(result, str) else "0x0"

    async def get_transaction_count(self, chain: str, address: str) -> int:
        result = await self.rpc_call("eth_getTransactionCount", [address, "latest"], chain=chain)
        return int(result, 16) if isinstance(result, str) and result else 0

    async def get_token_metadata(self, chain: str, address: str) -> dict[str, Any]:
        async def _eth_call(data_hex: str) -> str:
            params = [{"to": address, "data": data_hex}, "latest"]
            result = await self.rpc_call("eth_call", params, chain=chain)
            return result or "0x"

        name_hex = await _eth_call(ERC20_METADATA_ABI["name"])
        symbol_hex = await _eth_call(ERC20_METADATA_ABI["symbol"])
        decimals_hex = await _eth_call(ERC20_METADATA_ABI["decimals"])

        def _decode_hex_string(hex_str: str) -> str:
            try:
                raw = bytes.fromhex(hex_str[2:])
                if len(raw) >= 64:
                    offset = int.from_bytes(raw[:32], "big")
                    length = int.from_bytes(raw[offset + 32 : offset + 64], "big")
                    start = offset + 64
                    return raw[start : start + length].decode("utf-8", errors="replace")
                return raw.decode("utf-8", errors="replace").strip("\x00")
            except (ValueError, IndexError):
                return ""

        return {
            "name": _decode_hex_string(name_hex) or "Unknown",
            "symbol": _decode_hex_string(symbol_hex) or "???",
            "decimals": int(decimals_hex, 16) if decimals_hex and decimals_hex != "0x" else 18,
            "address": address,
        }

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
        result = await self.rpc_call(
            "eth_call",
            [{"to": MULTICALL3_ADDRESS, "data": data_hex}, "latest"],
            chain=chain,
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
        result = await self.rpc_call("trace_transaction", [tx_hash], chain=chain)
        if isinstance(result, list):
            return result[0] if result else {}
        return result if isinstance(result, dict) else {}

    async def close(self) -> None:
        await self._client.aclose()
