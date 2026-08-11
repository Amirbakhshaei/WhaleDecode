"""USD pricing for on-chain tokens via DeFiLlama.

Deterministic gate needs a *real* USD value for each candidate event. This
adapter resolves token → USD using the public DeFiLlama coins API, with a TTL
cache so a burst of transfers of the same token results in one HTTP call.
"""
import asyncio
import logging
from typing import Any

import httpx
from cachetools import TTLCache

logger = logging.getLogger(__name__)

DEFILLAMA_PRICE_URL = "https://coins.llama.fi/prices/current/{chain_id}:{contract_address}"

# ponytail: single module-level TTL cache shared by all oracle instances; 5-min
# staleness is fine for a $50k whale floor. Per-token locks dedupe concurrent
# lookups of the same contract during an ingestion burst.
_CACHE_TTL_SECONDS = 300
_CACHE_MAXSIZE = 2048

STABLECOINS = {"USDC", "USDT", "DAI", "FRAX", "TUSD", "USDP", "FDUSD", "USDE", "USDS"}

# CandidateEvent.chain → DeFiLlama chain id. Unlisted chains get priced at 0
# (conservative: the event is dropped rather than guessed).
CHAIN_TO_DEFILLAMA = {
    "ethereum": "ethereum",
    "eth": "ethereum",
    "mainnet": "ethereum",
    "bsc": "bsc",
    "bnb": "bsc",
    "polygon": "polygon",
    "matic": "polygon",
    "arbitrum": "arbitrum",
    "arbitrum_one": "arbitrum",
    "base": "base",
    "avalanche": "avax",
    "avax": "avax",
    "fantom": "fantom",
    "optimism": "optimism",
    "op": "optimism",
    "solana": "solana",
    "tron": "tron",
}


class PriceOracle:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        ttl_seconds: int = _CACHE_TTL_SECONDS,
        maxsize: int = _CACHE_MAXSIZE,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._cache: TTLCache[str, float] = TTLCache(maxsize=maxsize, ttl=ttl_seconds)
        self._locks: dict[str, asyncio.Lock] = {}

    async def get_token_price_usd(self, contract_address: str, chain: str) -> float:
        """Return the token's USD unit price, or ``0.0`` when unknown/unreachable.

        ``0.0`` is the conservative failure value: callers treat it as
        "no confirmed price" and drop the event rather than guess.
        """
        contract_address = (contract_address or "").strip()
        if not contract_address:
            return 0.0
        contract_address = contract_address.lower()

        key = f"{chain.lower()}:{contract_address}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            price = await self._fetch_price(contract_address, chain)
            self._cache[key] = price
            return price

    async def _fetch_price(self, contract_address: str, chain: str) -> float:
        chain_id = CHAIN_TO_DEFILLAMA.get(chain.lower())
        if not chain_id:
            logger.debug(f"Price lookup skipped: chain '{chain}' not priced")
            return 0.0
        try:
            response = await self._client.get(
                DEFILLAMA_PRICE_URL.format(chain_id=chain_id, contract_address=contract_address)
            )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
            coin = payload.get("coins", {}).get(f"{chain_id}:{contract_address}")
            if coin is None:
                return 0.0
            price = float(coin.get("price", 0.0) or 0.0)
            symbol = str(coin.get("symbol", "")).upper()
            if symbol in STABLECOINS:
                price = 1.0
            return price
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            logger.warning(f"Price lookup failed for {contract_address} on {chain}: {exc}")
            return 0.0

    async def aclose(self) -> None:
        await self._client.aclose()
