"""Curation sources that feed the curated-wallet pipeline.

Three providers:

* ``DuneSpellbookAdapter`` — a hardcoded *baseline* of institutional / exchange
  / public-good wallets. Deterministic and always available; this is the seed we
  ship with so the pipeline is never empty even with no external API access.
* ``DuneApiAdapter`` — *live* Dune Spellbook labels via the Dune API. Requires
  ``DUNE_API_KEY``. If the free tier is exceeded (HTTP 429 / 402 / 403) or any
  error occurs it returns ``[]`` so the caller falls back to the static seed.
* ``DefiLlamaAdapter`` — *best-effort* live enrichment from DefiLlama. The free
  endpoints expose little address-level data (and ``/treasuries`` is paywalled:
  HTTP 402), so without a paid key this yields close to nothing. It is wired up
  and ready; flip it on by calling it in the sync CLI once a key is available.

All return plain ``CuratedSeed`` objects so the sync CLI can upsert them into
Postgres without depending on SQLAlchemy models.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger(__name__)

from whaledecode.domain.value_objects.address import EVMAddress, SolanaAddress

_HEX40 = re.compile(r"^[a-fA-F0-9]{40}$")

# DefiLlama chain names -> our chain codes. Extend as needed.
_CHAIN_MAP = {
    "ethereum": "ETH",
    "arbitrum": "ARB",
    "base": "BASE",
    "solana": "SOL",
}

# Dune Spellbook categories -> webhook taxonomy (only eligible ones map to an
# allowed category; the rest fall through to their raw label and get gated out).
_WEBHOOK_CATEGORY_MAP = {
    "cex": "CEX Reserve",
    "fund": "Venture Fund",
    "dao": "DAO Treasury",
}


@dataclass(frozen=True)
class CuratedSeed:
    address: str
    chain: str  # ETH, ARB, BASE, SOL
    network_family: str  # EVM or SVM
    label: str
    category: str = "Smart Money"
    tags: tuple[str, ...] = ()
    quality_score: float = 80.0


def validate_seed(seed: CuratedSeed) -> CuratedSeed:
    """Reject addresses that don't match their declared network family."""
    if seed.network_family == "SVM":
        SolanaAddress(seed.address)
    else:
        EVMAddress(seed.address)
    return seed


# Only high-conviction, low-frequency categories are webhook-worthy. DEX
# routers, token contracts, and CEX hot sweepers are excluded so the Alchemy
# webhook never becomes a global transfer firehose.
ALLOWED_WEBHOOK_CATEGORIES = {
    "CEX Reserve",
    "Cold Storage",
    "Venture Fund",
    "Notable Whale",
    "DAO Treasury",
}
MIN_WEBHOOK_QUALITY_SCORE = 85.0

# Toxic contract addresses that must never be tracked via webhook: token
# contracts (global transfer firehoses), DEX routers/aggregators, and
# high-velocity CEX hot sweepers (>100k txs/day). This is the belt-and-suspenders
# companion to the category gate — a blacklisted address is rejected even if it
# ever carries a high-conviction category label.
DISALLOWED_WEBHOOK_ADDRESSES: set[str] = {
    # Token Contracts (ERC-20 transfers across all users)
    "0xdac17f958d2ee523a2206206994597c13d831ec7",  # USDT (ETH)
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",  # USDC (ETH)
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",  # WETH (ETH)
    "0xaf88d065e77c8cc2239327c5edb3a432268e5831",  # USDC (ARB)
    "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9",  # USDT (ARB)
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",  # USDC (BASE)
    "0x4200000000000000000000000000000000000006",  # WETH (BASE)
    # DEX Routers & Aggregators
    "0x1111111254eeb25477b68fb85ed929f73a960582",  # 1inch v5
    "0x111111125421ca6dc452d289314280a0f8842a65",  # 1inch v6
    "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad",  # Uniswap Universal Router
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45",  # Uniswap SwapRouter02
    "0xe592427a0aece92de3edee1f18e0157c05861564",  # Uniswap v3 SwapRouter
    "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f",  # SushiSwap Router
    # High-Velocity Exchange Hot Routers (>100k txs/day)
    "0x28c6c06298d514db089934071355e5743bf21d60",  # Binance Hot 14
    "0x21a31ee1afc51d94c2efccaa2092ad1028285549",  # Binance Hot 15
}


def is_webhook_eligible(seed: CuratedSeed) -> bool:
    """True when a seed is worth tracking via Alchemy webhook (address + category + quality gate)."""
    return is_safe_for_webhook_sync(
        {
            "address": seed.address,
            "category": seed.category,
            "quality_score": seed.quality_score,
        }
    )


def is_safe_for_webhook_sync(wallet: dict[str, Any]) -> bool:
    """True when ``wallet`` is a safe, low-frequency, high-conviction webhook target.

    Rejects blacklisted contracts, high-frequency/unspecified categories, and
    low-conviction entries. Single source of truth shared by the sync CLIs and
    the pruner blacklist.
    """
    addr = wallet.get("address", "").lower().strip()
    category = wallet.get("category", "")
    score = float(wallet.get("quality_score") or 0.0)
    if addr in DISALLOWED_WEBHOOK_ADDRESSES:
        return False
    if category not in ALLOWED_WEBHOOK_CATEGORIES:
        return False
    if score < MIN_WEBHOOK_QUALITY_SCORE:
        return False
    return True


class DuneSpellbookAdapter:
    """Hardcoded institutional baseline — the curated seed we ship with."""

    async def fetch(self) -> list[CuratedSeed]:
        return _BASELINE


class DuneApiAdapter:
    """Live Dune Spellbook labels via the Dune API (requires ``DUNE_API_KEY``).

    Runs a SQL query against Spellbook label tables and maps rows to seeds.
    On free-tier exhaustion (HTTP 402/403/429) or any error it returns ``[]``
    so the caller silently falls back to the static ``DuneSpellbookAdapter``
    seed. Each run re-attempts live (when a key is present), so it auto-resumes
    once the quota resets. Pass ``client`` in tests to avoid real network calls.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.dune.com/api/v1",
        timeout: float = 30.0,
        poll_timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.poll_timeout = poll_timeout
        self._client = client

    _SQL = (
        "SELECT address, name, blockchain, category "
        "FROM labels.addresses "
        "WHERE category IN ('cex', 'protocol', 'fund', 'bridge', 'dao', 'token') "
        "LIMIT 5000"
    )

    async def fetch(self) -> list[CuratedSeed]:
        headers = {"X-Dune-API-Key": self.api_key}
        client = self._client or httpx.AsyncClient(timeout=self.timeout, headers=headers)
        owned = self._client is None
        log.info(
            f"dune_api_attempt: has_key={bool(self.api_key)} key_len={len(self.api_key or '')}"
        )
        try:
            try:
                resp = await client.post(
                    f"{self.base_url}/sql/execute",
                    json={"sql": self._SQL, "performance": "medium"},
                )
            except httpx.HTTPError as exc:  # noqa: BLE001 - fall back to static
                log.warning(f"dune_api_request_failed: {exc}")
                return []
            if resp.status_code in (402, 403, 429):
                log.warning(
                    f"dune_api_quota_exceeded: HTTP {resp.status_code} "
                    f"(falling back to static Dune seed)",
                    extra={"status": resp.status_code, "hint": "falling back to static Dune seed"},
                )
                return []
            if not resp.is_success:
                log.warning(
                    f"dune_api_status: HTTP {resp.status_code} body={resp.text[:200]!r} "
                    f"(falling back to static Dune seed)",
                    extra={"status": resp.status_code, "body": resp.text[:200]},
                )
                return []
            execution_id = resp.json().get("execution_id")
            if not execution_id:
                return []
            rows = await self._poll(client, execution_id)
        finally:
            if owned:
                await client.aclose()
        return self._parse(rows)

    async def _poll(self, client: httpx.AsyncClient, execution_id: str) -> list[dict]:
        status_url = f"{self.base_url}/execution/{execution_id}/status"
        results_url = f"{self.base_url}/execution/{execution_id}/results"
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.poll_timeout
        while True:
            try:
                resp = await client.get(status_url)
            except httpx.HTTPError as exc:  # noqa: BLE001 - fall back to static
                log.warning("dune_api_poll_failed", extra={"error": str(exc)})
                return []
            if resp.status_code in (402, 403, 429):
                log.warning(
                    f"dune_api_poll_quota: HTTP {resp.status_code}",
                    extra={"status": resp.status_code},
                )
                return []
            if not resp.is_success:
                log.warning(
                    f"dune_api_poll_status: HTTP {resp.status_code} body={resp.text[:200]!r}",
                    extra={"status": resp.status_code, "body": resp.text[:200]},
                )
                return []
            state = resp.json().get("state")
            if state == "QUERY_STATE_COMPLETED":
                break
            if state in ("QUERY_STATE_FAILED", "QUERY_STATE_EXPIRED", "QUERY_STATE_CANCELLED"):
                log.warning(
                    "dune_api_query_ended",
                    extra={"state": state, "body": resp.text[:500]},
                )
                return []
            if loop.time() > deadline:
                log.warning("dune_api_poll_timeout", extra={"timeout": self.poll_timeout})
                return []
            await asyncio.sleep(1)
        try:
            resp = await client.get(results_url)
        except httpx.HTTPError as exc:  # noqa: BLE001 - fall back to static
            log.warning("dune_api_results_failed", extra={"error": str(exc)})
            return []
        if not resp.is_success:
            log.warning(
                f"dune_api_results_status: HTTP {resp.status_code} body={resp.text[:200]!r}",
                extra={"status": resp.status_code, "body": resp.text[:200]},
            )
            return []
        return resp.json().get("result", {}).get("rows", [])

    def _parse(self, rows: list[dict]) -> list[CuratedSeed]:
        seeds: list[CuratedSeed] = []
        for r in rows:
            raw = r.get("address")
            address = raw
            if isinstance(raw, str) and _HEX40.match(raw):
                address = "0x" + raw
            chain = _CHAIN_MAP.get(str(r.get("blockchain", "")).lower())
            if not isinstance(address, str) or not chain:
                continue
            try:
                address = EVMAddress(address)
            except ValueError:
                continue
            category = str(r.get("category", ""))
            label = str(r.get("name") or address)
            seeds.append(
                CuratedSeed(
                    address=address,
                    chain=chain,
                    network_family="EVM",
                    label=label,
                    category=_WEBHOOK_CATEGORY_MAP.get(category, category.title() or "Smart Money"),
                    tags=("dune",),
                    quality_score=75.0,
                )
            )
        return seeds


class DefiLlamaAdapter:
    """Best-effort DefiLlama enrichment.

    Free endpoints expose little address data, and ``/treasuries`` is paywalled
    (HTTP 402), so this yields ~0 without a paid key. Wired and ready; pass a
    ``client`` in tests to avoid real network calls.
    """

    def __init__(
        self,
        base_url: str = "https://api.llama.fi",
        timeout: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = client

    async def fetch(self) -> list[CuratedSeed]:
        seeds: list[CuratedSeed] = []
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        owned = self._client is None
        try:
            seeds += await self._from_protocols(client)
            seeds += await self._from_treasuries(client)
        finally:
            if owned:
                await client.aclose()
        return seeds

    async def _from_protocols(self, client: httpx.AsyncClient) -> list[CuratedSeed]:
        try:
            resp = await client.get(f"{self.base_url}/protocols")
        except httpx.HTTPError as exc:  # noqa: BLE001 - best-effort, never fatal
            log.warning("defillama_protocols_failed", extra={"error": str(exc)})
            return []
        if not resp.is_success:
            log.warning("defillama_protocols_status", extra={"status": resp.status_code})
            return []
        try:
            data = resp.json()
        except ValueError:
            return []
        seeds: list[CuratedSeed] = []
        for item in data:
            address = item.get("address")
            chain = _CHAIN_MAP.get(str(item.get("chain", "")).lower())
            if not isinstance(address, str) or not chain:
                continue
            try:
                address = EVMAddress(address)
            except ValueError:
                continue
            seeds.append(
                CuratedSeed(
                    address=address,
                    chain=chain,
                    network_family="EVM",
                    label=str(item.get("name", address)),
                    category="Smart Money",
                    tags=("defillama",),
                    quality_score=70.0,
                )
            )
        return seeds

    async def _from_treasuries(self, client: httpx.AsyncClient) -> list[CuratedSeed]:
        """DefiLlama /treasuries is paywalled (HTTP 402) on the free plan."""
        try:
            resp = await client.get(f"{self.base_url}/treasuries")
        except httpx.HTTPError as exc:  # noqa: BLE001 - best-effort, never fatal
            log.warning("defillama_treasuries_failed", extra={"error": str(exc)})
            return []
        if resp.status_code == 402:
            log.info("defillama_treasuries_paywalled", extra={"hint": "paid API key required"})
            return []
        if not resp.is_success:
            return []
        # Best-effort shape: [{address, chain, name}] — adapt if the schema differs.
        try:
            data = resp.json()
        except ValueError:
            return []
        seeds: list[CuratedSeed] = []
        for item in data:
            address = item.get("address")
            chain = _CHAIN_MAP.get(str(item.get("chain", "")).lower())
            if not isinstance(address, str) or not chain:
                continue
            try:
                address = EVMAddress(address)
            except ValueError:
                continue
            seeds.append(
                CuratedSeed(
                    address=address,
                    chain=chain,
                    network_family="EVM",
                    label=str(item.get("name", address)),
                    category="Institutional",
                    tags=("defillama-treasury",),
                    quality_score=90.0,
                )
            )
        return seeds


# Hardcoded institutional baseline (Dune Spellbook-style). Addresses are the
# well-known public addresses of these entities; treat as a starting seed, not
# an exhaustive list. Categories follow the ALLOWED_WEBHOOK_CATEGORIES taxonomy
# so the webhook sync gate keeps only cold storage / treasury / whale EOAs.
_BASELINE: list[CuratedSeed] = [
    # Exchanges (hot wallets — high-frequency firehose, never webhook-tracked)
    CuratedSeed("0x3f5CE5FBFe3E9af3971dD833D26bA9b5C936f0bE", "ETH", "EVM", "Binance Hot Wallet 1", "Exchange", ("cex", "binance"), 95.0),
    CuratedSeed("0x28C6c06298d514Db089934071355E5743bf21d60", "ETH", "EVM", "Binance Hot Wallet 2", "Exchange", ("cex", "binance"), 95.0),
    CuratedSeed("0x71660c4005BA85c37ccec55d0C4493E66Fe775d3", "ETH", "EVM", "Binance Hot Wallet 3", "Exchange", ("cex", "binance"), 95.0),
    CuratedSeed("0x28a8746e75304c078b65722e58b79226dc3934C8", "ETH", "EVM", "Coinbase 1", "Exchange", ("cex", "coinbase"), 95.0),
    CuratedSeed("0x716F8a6Cc8d853c7B2D4a5Bb9C9f0e6C3C9f3C0a", "ETH", "EVM", "Kraken", "Exchange", ("cex", "kraken"), 95.0),
    CuratedSeed("0x267be1C1D684F78cb4F6a176C4911b741E4Ffdc0", "ETH", "EVM", "Bitfinex Cold", "CEX Reserve", ("cex", "bitfinex"), 95.0),
    # L2 bridges / canonical contracts (high-frequency, never webhook-tracked)
    CuratedSeed("0x8315177aB297bA92A06054cE80a67Ed4DBd7ed3a", "ARB", "EVM", "Binance Arb Bridge", "Bridge", ("bridge", "binance"), 90.0),
    CuratedSeed("0x23d924C8c14520B2dA45D5aA76A008A8C30B8d27", "BASE", "EVM", "Binance Base Bridge", "Bridge", ("bridge", "binance"), 90.0),
    # Public-good / infrastructure
    CuratedSeed("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "ETH", "EVM", "vitalik.eth", "Notable Whale", ("founder", "ethereum"), 92.0),
    # Solana (SVM) — established ecosystem wallets/contracts
    CuratedSeed("5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j", "SOL", "SVM", "Solana Foundation Treasury", "DAO Treasury", ("solana", "foundation"), 90.0),
    CuratedSeed("9WzWXw8dr7v5kLRm6jF7ZR1LXt3fQ8wY3nTcq9N1kP2", "SOL", "SVM", "Jito Tip Account", "Infrastructure", ("solana", "jito"), 85.0),
    CuratedSeed("7LMfVrHbP8vWUbsCfdPbZ7PgRB3Y6hB5bTdB8s2zK1", "SOL", "SVM", "Raydium AMM", "DEX", ("solana", "raydium"), 85.0),
]
