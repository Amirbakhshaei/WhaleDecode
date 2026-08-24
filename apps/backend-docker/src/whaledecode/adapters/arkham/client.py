"""Arkham Intelligence API fallback (Module 1, Option B half).

For wallets with no self-observed history: fetch a coarse PnL/label snapshot.
Free tier is rate-limited and undocumented — every failure degrades to an
empty dict so the profiler falls back to "Unknown".
"""
import logging
from typing import Any

from whaledecode.infrastructure.http import HttpClientManager

logger = logging.getLogger(__name__)

ARKHAM_BASE = "https://api.arkhamintelligence.com"


class ArkhamClient:
    def __init__(self, api_key: str, timeout_seconds: float = 8.0) -> None:
        self._api_key = api_key
        self._timeout = timeout_seconds

    async def wallet_snapshot(self, chain: str, address: str) -> dict[str, Any]:
        """Best-effort {pnl_usd, label} for an address; {} on any failure."""
        if not self._api_key or not address:
            return {}
        client = HttpClientManager.get_client("arkham", timeout=self._timeout)
        try:
            response = await client.get(
                f"{ARKHAM_BASE}/intelligence/address",
                params={"chain": chain.lower(), "address": address.lower()},
                headers={"x-api-key": self._api_key},
            )
            response.raise_for_status()
            data = response.json()
            return {
                "pnl_usd": float(data.get("pnlUsd") or data.get("usd", {}).get("pnl") or 0.0),
                "label": str(data.get("labelName") or ""),
            }
        except Exception as exc:
            logger.warning(f"arkham snapshot failed for {address}: {exc}")
            return {}
