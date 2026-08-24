"""Alchemy Transfers API adapter (Module 2 data source).

Thin wrapper over ``alchemy_getAssetTransfers`` — the same Alchemy account
already provisioned for webhooks covers these CUs. All methods fail soft:
missing RPC metadata / timeouts return empty lists, never raise.
"""
import logging
from typing import Any

from whaledecode.config.settings import Settings
from whaledecode.infrastructure.http import HttpClientManager

logger = logging.getLogger(__name__)

# chain name -> Alchemy network subdomain
_NETWORKS = {
    "ethereum": "eth-mainnet",
    "eth": "eth-mainnet",
    "arbitrum": "arb-mainnet",
    "arb": "arb-mainnet",
    "base": "base-mainnet",
}


def _network(chain: str) -> str:
    return _NETWORKS.get(chain.strip().lower(), "")


class AlchemyTransfersClient:
    def __init__(self, api_key: str, timeout_seconds: float = 10.0) -> None:
        self._api_key = api_key
        self._timeout = timeout_seconds

    @classmethod
    def from_settings(cls, settings: Settings) -> "AlchemyTransfersClient":
        key = settings.ALCHEMY_API_KEY.get_secret_value() if settings.ALCHEMY_API_KEY else ""
        return cls(api_key=key)

    async def incoming_transfers(
        self, chain: str, to_address: str, *, max_count: int = 20
    ) -> list[dict[str, Any]]:
        """Transfers received by ``to_address`` (native + ERC-20), newest first."""
        network = _network(chain)
        to_address = (to_address or "").strip().lower()
        if not network or not to_address or not self._api_key:
            return []
        url = f"https://{network}.g.alchemy.com/v2/{self._api_key}"
        client = HttpClientManager.get_client("alchemy-transfers", timeout=self._timeout)
        try:
            response = await client.post(
                url,
                json={
                    "id": 1,
                    "jsonrpc": "2.0",
                    "method": "alchemy_getAssetTransfers",
                    "params": [
                        {
                            "toAddress": to_address,
                            "category": ["external", "internal", "erc20"],
                            "maxCount": hex(max_count),
                            "order": "desc",
                            "withMetadata": True,
                        }
                    ],
                },
            )
            response.raise_for_status()
            result = response.json().get("result") or {}
            return list(result.get("transfers") or [])
        except Exception as exc:  # httpx errors, JSON errors — tracer degrades gracefully
            logger.warning(f"alchemy transfers lookup failed for {to_address}: {exc}")
            return []
