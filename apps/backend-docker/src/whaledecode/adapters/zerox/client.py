"""0x Swap API v2 adapter (Module 4 execution layer).

Deterministic quotes fetched on-demand when a *user taps* a swap button —
never on the alert critical path (zero-latency directive). The protocol fee
(0.8% default) rides via v2 ``swapFeeBps`` / ``swapFeeRecipient`` params;
every failure degrades to an empty dict so UX falls back to the Matcha
deep-link without a live quote.
"""
import logging
from typing import Any

import httpx
from whaledecode.infrastructure.http import HttpClientManager

logger = logging.getLogger(__name__)

ZEROX_BASE = "https://api.0x.org"

# chain name -> 0x v2 chain id
CHAIN_IDS = {
    "ethereum": "1",
    "eth": "1",
    "base": "8453",
    "base_mainnet": "8453",
    "arbitrum": "42161",
    "arb": "42161",
}

NATIVE_SELL = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"  # ETH as ERC-20 alias


def chain_id(chain: str) -> str:
    return CHAIN_IDS.get(chain.strip().lower(), "")


class ZeroXClient:
    def __init__(self, api_key: str, timeout_seconds: float = 8.0) -> None:
        self._api_key = api_key
        self._timeout = timeout_seconds

    @classmethod
    def from_settings(cls, settings: Any) -> "ZeroXClient":
        key = settings.ZEROX_API_KEY.get_secret_value() if getattr(settings, "ZEROX_API_KEY", None) else ""
        return cls(api_key=key)

    async def quote(
        self,
        chain: str,
        buy_token: str,
        sell_amount_wei: int,
        *,
        fee_recipient_bps: tuple[str, int] | None = None,
        taker: str = "",
    ) -> dict[str, Any]:
        """GET /swap/permit2/quote — returns the executable transaction payload
        (``to``, ``data``, ``value``, plus ``buyAmount`` / expected slippage).
        {} on any failure."""
        chain_key = chain_id(chain)
        if not chain_key or not buy_token or sell_amount_wei <= 0:
            return {}
        params: dict[str, Any] = {
            "sellToken": NATIVE_SELL,
            "buyToken": buy_token,
            "sellAmount": str(sell_amount_wei),
            "slippageBps": "100",  # 1% protective ceiling
            "excludedSources": "RFQ",
        }
        if taker:
            params["taker"] = taker
        if fee_recipient_bps:
            recipient, bps = fee_recipient_bps
            if recipient and bps > 0:
                params["swapFeeRecipient"] = recipient
                params["swapFeeBps"] = str(bps)
                params["swapFeeToken"] = buy_token
        headers = {"0x-version": "v2"}
        if self._api_key:
            headers["0x-api-key"] = self._api_key
        client = HttpClientManager.get_client("zerox", timeout=self._timeout)
        try:
            response = await client.get(
                f"{ZEROX_BASE}/swap/permit2/quote/{chain_key}",
                params=params,
                headers=headers,
            )
            response.raise_for_status()
            return dict(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(f"0x v2 quote failed ({chain} {buy_token}): {exc}")
            return {}


def wei(amount_eth: float) -> int:
    """ETH whole units -> wei (int math avoids float drift at typical sizes)."""
    return int(round(amount_eth * 10**18))
