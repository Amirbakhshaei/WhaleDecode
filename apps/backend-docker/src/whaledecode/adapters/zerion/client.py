"""Zerion API adapter (Module 1 cold-start fallback).

Replaces the Arkham fallback: free Developer tier ($0, 2K req/day, 3 RPS)
covers realized + unrealized wallet PnL across 40+ chains including Solana.
Only called from background backfill paths — never on the alert critical
path (zero-latency directive). Every failure degrades to an empty dict so
the profiler keeps its baseline behavior.
"""
import logging
from typing import Any

from whaledecode.infrastructure.http import HttpClientManager

logger = logging.getLogger(__name__)

ZERION_BASE = "https://api.zerion.io/v1"

# our chain names -> Zerion chain ids (they use the same lowercase slugs).
CHAIN_IDS = {
    "ethereum": "ethereum",
    "eth": "ethereum",
    "base": "base",
    "arbitrum": "arbitrum",
    "arb": "arbitrum",
    "solana": "solana",
    "sol": "solana",
}


class ZerionClient:
    def __init__(self, api_key: str, timeout_seconds: float = 8.0) -> None:
        self._api_key = api_key
        self._timeout = timeout_seconds

    @classmethod
    def from_settings(cls, settings: Any) -> "ZerionClient":
        key = settings.ZERION_API_KEY.get_secret_value() if getattr(settings, "ZERION_API_KEY", None) else ""
        return cls(api_key=key)

    async def wallet_snapshot(self, chain: str, address: str) -> dict[str, Any]:
        """Best-effort {pnl_usd, label} for an address; {} on any failure."""
        if not self._api_key or not address:
            return {}
        chain_id = CHAIN_IDS.get(chain.strip().lower(), "")
        if not chain_id:
            return {}
        client = HttpClientManager.get_client("zerion", timeout=self._timeout)
        try:
            response = await client.get(
                f"{ZERION_BASE}/wallets/{address.lower()}/pnl",
                params={"filter[chain_ids]": chain_id},
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            response.raise_for_status()
            attrs: dict[str, Any] = (response.json().get("data") or {}).get("attributes") or {}
            # ponytail: Zerion's numeric fields have drifted between float and
            # string across versions; coerce defensively instead of trusting.
            pnl = _to_float(attrs.get("total_pnl")) or (
                (_to_float(attrs.get("realized_pnl")) or 0.0)
                + (_to_float(attrs.get("unrealized_pnl")) or 0.0)
            )
            return {"pnl_usd": pnl, "label": ""}
        except Exception as exc:
            logger.warning(f"zerion snapshot failed for {address}: {exc}")
            return {}


def _to_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed
