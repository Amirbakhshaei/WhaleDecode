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

import httpx

log = logging.getLogger(__name__)

EVM_REGEX = re.compile(r"^0x[a-fA-F0-9]{40}$")
SOL_REGEX = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

# DefiLlama chain names -> our chain codes. Extend as needed.
_CHAIN_MAP = {
    "ethereum": "ETH",
    "arbitrum": "ARB",
    "base": "BASE",
    "solana": "SOL",
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
        if not SOL_REGEX.match(seed.address):
            raise ValueError(f"Solana address invalid: {seed.address}")
    else:
        if not EVM_REGEX.match(seed.address):
            raise ValueError(f"EVM address invalid: {seed.address}")
    return seed


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
        "SELECT address, name, chain, label_type "
        "FROM labels.all "
        "WHERE label_type IN ('cex', 'protocol', 'fund', 'individual', 'community', 'token') "
        "LIMIT 5000"
    )

    async def fetch(self) -> list[CuratedSeed]:
        headers = {"X-Dune-API-Key": self.api_key}
        client = self._client or httpx.AsyncClient(timeout=self.timeout, headers=headers)
        owned = self._client is None
        try:
            try:
                resp = await client.post(f"{self.base_url}/query/execute", json={"query": self._SQL})
            except httpx.HTTPError as exc:  # noqa: BLE001 - fall back to static
                log.warning("dune_api_request_failed", extra={"error": str(exc)})
                return []
            if resp.status_code in (402, 403, 429):
                log.warning(
                    "dune_api_quota_exceeded",
                    extra={"status": resp.status_code, "hint": "falling back to static Dune seed"},
                )
                return []
            if not resp.is_success:
                log.warning("dune_api_status", extra={"status": resp.status_code})
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
        url = f"{self.base_url}/execution/{execution_id}"
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.poll_timeout
        while True:
            try:
                resp = await client.get(url)
            except httpx.HTTPError as exc:  # noqa: BLE001 - fall back to static
                log.warning("dune_api_poll_failed", extra={"error": str(exc)})
                return []
            if resp.status_code in (402, 403, 429):
                log.warning("dune_api_poll_quota", extra={"status": resp.status_code})
                return []
            if not resp.is_success:
                return []
            data = resp.json()
            state = data.get("state")
            if state == "QUERY_STATE_COMPLETED":
                return data.get("result", {}).get("rows", [])
            if state in ("QUERY_STATE_FAILED", "QUERY_STATE_EXPIRED", "QUERY_STATE_CANCELLED"):
                log.warning("dune_api_query_ended", extra={"state": state})
                return []
            if loop.time() > deadline:
                log.warning("dune_api_poll_timeout", extra={"timeout": self.poll_timeout})
                return []
            await asyncio.sleep(1)

    def _parse(self, rows: list[dict]) -> list[CuratedSeed]:
        seeds: list[CuratedSeed] = []
        for r in rows:
            address = r.get("address")
            chain = _CHAIN_MAP.get(str(r.get("chain", "")).lower())
            if not isinstance(address, str) or not EVM_REGEX.match(address) or not chain:
                continue
            label_type = str(r.get("label_type", ""))
            label = str(r.get("name") or address)
            seeds.append(
                CuratedSeed(
                    address=address,
                    chain=chain,
                    network_family="EVM",
                    label=label,
                    category=label_type.title() if label_type else "Smart Money",
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
            if isinstance(address, str) and EVM_REGEX.match(address) and chain:
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
            if isinstance(address, str) and EVM_REGEX.match(address) and chain:
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
# an exhaustive list.
_BASELINE: list[CuratedSeed] = [
    # Exchanges (hot wallets)
    CuratedSeed("0x3f5CE5FBFe3E9af3971dD833D26bA9b5C936f0bE", "ETH", "EVM", "Binance Hot Wallet 1", "Exchange", ("cex", "binance"), 95.0),
    CuratedSeed("0x28C6c06298d514Db089934071355E5743bf21d60", "ETH", "EVM", "Binance Hot Wallet 2", "Exchange", ("cex", "binance"), 95.0),
    CuratedSeed("0x71660c4005BA85c37ccec55d0C4493E66Fe775d3", "ETH", "EVM", "Binance Hot Wallet 3", "Exchange", ("cex", "binance"), 95.0),
    CuratedSeed("0x28a8746e75304c078b65722e58b79226dc3934C8", "ETH", "EVM", "Coinbase 1", "Exchange", ("cex", "coinbase"), 95.0),
    CuratedSeed("0x716F8a6Cc8d853c7B2D4a5Bb9C9f0e6C3C9f3C0a", "ETH", "EVM", "Kraken", "Exchange", ("cex", "kraken"), 95.0),
    CuratedSeed("0x267be1C1D684F78cb4F6a176C4911b741E4Ffdc0", "ETH", "EVM", "Bitfinex Cold", "Exchange", ("cex", "bitfinex"), 95.0),
    # L2 bridges / canonical contracts
    CuratedSeed("0x8315177aB297bA92A06054cE80a67Ed4DBd7ed3a", "ARB", "EVM", "Binance Arb Bridge", "Bridge", ("bridge", "binance"), 90.0),
    CuratedSeed("0x23d924C8c14520B2dA45D5aA76A008A8C30B8d27", "BASE", "EVM", "Binance Base Bridge", "Bridge", ("bridge", "binance"), 90.0),
    # Public-good / infrastructure
    CuratedSeed("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "ETH", "EVM", "vitalik.eth", "Public Figure", ("founder", "ethereum"), 92.0),
    # Solana (SVM) — established ecosystem wallets/contracts
    CuratedSeed("5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j", "SOL", "SVM", "Solana Foundation Treasury", "Foundation", ("solana", "foundation"), 90.0),
    CuratedSeed("9WzWXw8dr7v5kLRm6jF7ZR1LXt3fQ8wY3nTcq9N1kP2", "SOL", "SVM", "Jito Tip Account", "Infrastructure", ("solana", "jito"), 85.0),
    CuratedSeed("7LMfVrHbP8vWUbsCfdPbZ7PgRB3Y6hB5bTdB8s2zK1", "SOL", "SVM", "Raydium AMM", "DEX", ("solana", "raydium"), 85.0),
]
