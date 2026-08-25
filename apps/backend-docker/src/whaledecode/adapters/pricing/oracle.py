"""USD pricing for on-chain tokens via DeFiLlama + CoinGecko.

Deterministic gate needs a *real* USD value for each candidate event. This
adapter resolves token → USD using DeFiLlama's public coins API, with TTL
caches so a burst of transfers of the same token results in one HTTP call.
Also captures the token symbol (for LLM context) and derives key price
levels (24h/7d/30d high-low + recent daily closes) from CoinGecko OHLC.
"""
import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from cachetools import TTLCache

logger = logging.getLogger(__name__)

DEFILLAMA_PRICE_URL = "https://coins.llama.fi/prices/current/{chain_id}:{contract_address}"
DEFILLAMA_HISTORICAL_URL = "https://coins.llama.fi/prices/historical/{unix_ts}/{chain_id}:{contract_address}"
COINGECKO_OHLC_URL = "https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
COINGECKO_LIST_URL = "https://api.coingecko.com/api/v3/coins/list"

# ponytail: module-level TTL caches shared by all oracle instances; 5-min price
# staleness is fine for a $50k whale floor. Per-key locks dedupe concurrent
# lookups of the same contract during an ingestion burst.
_CACHE_TTL_SECONDS = 300
_CACHE_MAXSIZE = 2048

# Recent timestamps (within this window) are served from the cheap current-price
# cache instead of an extra historical call; whales are analyzed within minutes
# of the block, so event-time ≈ now.
_LOOKBACK_SECONDS = 3600

# Candle-derived levels are stable for an hour and per-contract.
_LEVEL_TTL_SECONDS = 3600
_LEVEL_MAXSIZE = 256

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

# CandidateEvent.chain → CoinGecko platform id (used for contract → coin resolution).
CHAIN_TO_COINGECKO = {
    "ethereum": "ethereum",
    "eth": "ethereum",
    "mainnet": "ethereum",
    "bsc": "binance-smart-chain",
    "bnb": "binance-smart-chain",
    "polygon": "polygon-pos",
    "matic": "polygon-pos",
    "arbitrum": "arbitrum-one",
    "arbitrum_one": "arbitrum-one",
    "base": "base",
    "avalanche": "avalanche",
    "avax": "avalanche",
    "fantom": "fantom",
    "optimism": "optimistic-ethereum",
    "op": "optimistic-ethereum",
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
        # key -> (price_usd, symbol)
        self._cache: TTLCache[str, tuple[float, str]] = TTLCache(maxsize=maxsize, ttl=ttl_seconds)
        # historical per-day-bucket cache: (chain:contract:day) -> price
        self._hist_cache: TTLCache[str, float] = TTLCache(maxsize=maxsize, ttl=ttl_seconds)
        self._level_cache: TTLCache[str, dict] = TTLCache(maxsize=_LEVEL_MAXSIZE, ttl=_LEVEL_TTL_SECONDS)
        self._locks: dict[str, asyncio.Lock] = {}
        # (platform:contract) -> coingecko coin id, built once per session (ponytail:
        # ~5MB list; empty dict caches a failed fetch for the session too).
        self._coin_map: dict[str, str] | None = None

    async def get_token_price_usd(self, contract_address: str, chain: str) -> float:
        """Return the token's current USD unit price, or ``0.0`` when unknown.

        ``0.0`` is the conservative failure value: callers treat it as
        "no confirmed price" and drop the event rather than guess.
        """
        return (await self._priced(contract_address, chain))[0]

    async def get_token_symbol(self, contract_address: str, chain: str) -> str:
        """Return the token symbol (e.g. ``SHIB``), or ``""`` when unknown.

        Best-effort; the symbol may only be known after a price lookup has run.
        """
        return (await self._priced(contract_address, chain))[1]

    async def _priced(self, contract_address: str, chain: str) -> tuple[float, str]:
        contract_address = (contract_address or "").strip()
        if not contract_address:
            return (0.0, "")
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
            result = await self._fetch_price(contract_address, chain)
            self._cache[key] = result
            return result

    async def get_token_price_usd_at(self, contract_address: str, chain: str, unix_ts: float) -> float:
        """Return the token's USD unit price at ``unix_ts`` (event time).

        Recent timestamps reuse the current-price cache (whales are analyzed
        minutes after the block). Older timestamps hit DeFiLlama's historical
        endpoint, cached per-contract-per-day so a burst of events in the same
        day bucket is one call.
        """
        if unix_ts >= time.time() - _LOOKBACK_SECONDS:
            return await self.get_token_price_usd(contract_address, chain)

        contract_address = (contract_address or "").strip().lower()
        if not contract_address:
            return 0.0

        key = f"{chain.lower()}:{contract_address}:{int(unix_ts // 86400)}"
        cached = self._hist_cache.get(key)
        if cached is not None:
            return cached

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self._hist_cache.get(key)
            if cached is not None:
                return cached
            price = await self._fetch_historical_price(contract_address, chain, unix_ts)
            self._hist_cache[key] = price
            return price

    async def get_price_levels(self, contract_address: str, chain: str) -> dict:
        """Return key price levels (USD) for the LLM, or ``{}`` when unknown.

        ``{"24h"/"7d"/"30d": {"high","low"}, "daily_closes": [..5 most recent..]}``
        Derived from one CoinGecko OHLC call (30d of 4h candles). ``{}`` on any
        failure — the LLM context renders it as "Unavailable".
        """
        contract_address = (contract_address or "").strip().lower()
        if not contract_address:
            return {}

        key = f"{chain.lower()}:{contract_address}"
        cached = self._level_cache.get(key)
        if cached is not None:
            return cached

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self._level_cache.get(key)
            if cached is not None:
                return cached
            levels = await self._fetch_price_levels(contract_address, chain)
            if levels:
                self._level_cache[key] = levels
            return levels

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- fetching -----------------------------------------------------------

    async def _fetch_price(self, contract_address: str, chain: str) -> tuple[float, str]:
        chain_id = CHAIN_TO_DEFILLAMA.get(chain.lower())
        if not chain_id:
            logger.debug(f"Price lookup skipped: chain '{chain}' not priced")
            return (0.0, "")
        try:
            response = await self._client.get(
                DEFILLAMA_PRICE_URL.format(chain_id=chain_id, contract_address=contract_address)
            )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
            coin = payload.get("coins", {}).get(f"{chain_id}:{contract_address}")
            if coin is None:
                return (0.0, "")
            price = float(coin.get("price", 0.0) or 0.0)
            symbol = str(coin.get("symbol", "") or "").upper()
            if symbol in STABLECOINS:
                price = 1.0
            return (price, symbol)
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            logger.warning(f"Price lookup failed for {contract_address} on {chain}: {exc}")
            return (0.0, "")

    async def _fetch_historical_price(self, contract_address: str, chain: str, unix_ts: float) -> float:
        chain_id = CHAIN_TO_DEFILLAMA.get(chain.lower())
        if not chain_id:
            return 0.0
        try:
            response = await self._client.get(
                DEFILLAMA_HISTORICAL_URL.format(unix_ts=int(unix_ts), chain_id=chain_id, contract_address=contract_address)
            )
            response.raise_for_status()
            coin = response.json().get("coins", {}).get(f"{chain_id}:{contract_address}")
            if coin is None:
                return 0.0
            return float(coin.get("price", 0.0) or 0.0)
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            logger.warning(f"Historical price lookup failed for {contract_address} on {chain}: {exc}")
            return 0.0

    async def _fetch_price_levels(self, contract_address: str, chain: str) -> dict:
        coin_id = await self._resolve_coin_id(contract_address, chain)
        if not coin_id:
            return {}
        try:
            response = await self._client.get(
                COINGECKO_OHLC_URL.format(coin_id=coin_id),
                params={"vs_currency": "usd", "days": 30},
            )
            response.raise_for_status()
            candles = response.json()
            if not isinstance(candles, list) or not candles or not isinstance(candles[0], list):
                return {}
            return _levels_from_candles(candles)
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            logger.warning(f"OHLC lookup failed for {contract_address} on {chain}: {exc}")
            return {}

    async def _resolve_coin_id(self, contract_address: str, chain: str) -> str:
        platform = CHAIN_TO_COINGECKO.get(chain.lower())
        if not platform:
            return ""
        coin_map = await self._get_coin_map()
        return coin_map.get(f"{platform}:{contract_address}", "")

    async def _get_coin_map(self) -> dict[str, str]:
        if self._coin_map is None:
            try:
                response = await self._client.get(COINGECKO_LIST_URL, params={"include_platform": True})
                response.raise_for_status()
                coin_map: dict[str, str] = {}
                for coin in response.json():
                    for platform, address in (coin.get("platforms") or {}).items():
                        if address:
                            coin_map[f"{platform}:{str(address).lower()}"] = coin["id"]
                self._coin_map = coin_map
            except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
                logger.warning(f"CoinGecko coin list failed: {exc}")
                self._coin_map = {}
        return self._coin_map


def _levels_from_candles(candles: list) -> dict:
    """Aggregate 4h OHLC candles into 24h/7d/30d high-low + recent daily closes.

    Candles are ``[timestamp_ms, open, high, low, close]``. 6 candles per day,
    so buckets are computed by calendar day/week to stay robust to boundary jitter.
    Returns only the high/low per window — close is redundant (≈ current price)
    and the goal is lean LLM context.
    """
    def _hl(points: list[list]) -> dict[str, float]:
        highs = [p[2] for p in points]
        lows = [p[3] for p in points]
        return {"high": round(max(highs), 8), "low": round(min(lows), 8)}

    daily: dict[Any, list[list]] = {}
    for candle in candles:
        day = datetime.fromtimestamp(candle[0] / 1000, UTC).date()
        daily.setdefault(day, []).append(candle)
    ordered_days = sorted(daily)

    recent = candles[-6:]  # last 24h
    week = candles[-42:]  # last 7 days (or fewer if data is short)
    return {
        "24h": _hl(recent) if recent else {},
        "7d": _hl(week) if week else {},
        "30d": _hl(candles),
        "daily_closes": [round(daily[d][-1][4], 8) for d in ordered_days[-5:]],
    }
