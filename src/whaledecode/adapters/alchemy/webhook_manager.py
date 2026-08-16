"""Alchemy Notify API webhook management."""
import logging

from whaledecode.config.settings import Settings
from whaledecode.infrastructure.http import HttpClientManager

logger = logging.getLogger(__name__)

_CHAINS = ("ETH", "ARB", "BASE")


class AlchemyWebhookManager:
    def __init__(self, alchemy_auth_token: str, webhook_ids: dict[str, str] | None = None) -> None:
        """
        Args:
            alchemy_auth_token: Notify API Auth Token (Dashboard -> Data -> Webhooks -> Auth Token).
            webhook_ids: Mapping of chain code ("ETH"/"ARB"/"BASE") -> Alchemy webhook ID.
        """
        self.auth_token = alchemy_auth_token
        self.webhook_ids = webhook_ids or {}
        self.base_url = "https://dashboard.alchemy.com/api"

    @classmethod
    def from_settings(cls, settings: Settings) -> "AlchemyWebhookManager":
        """Build the manager from env config: notify token + the three per-chain webhook IDs."""
        token = settings.ALCHEMY_NOTIFY_TOKEN or settings.ALCHEMY_AUTH_TOKEN
        token = token.get_secret_value() if token else ""
        webhook_ids = {chain: getattr(settings, f"ALCHEMY_WEBHOOK_ID_{chain}") for chain in _CHAINS}
        return cls(alchemy_auth_token=token, webhook_ids=webhook_ids)

    async def sync_addresses(self, addresses: list[str]) -> None:
        """Add ``addresses`` to every configured chain webhook.

        Logs the HTTP status per chain; a missing webhook ID for a chain is
        skipped rather than fatal.
        """
        for chain, webhook_id in self.webhook_ids.items():
            if not webhook_id:
                logger.warning(f"Skipping {chain}: no ALCHEMY_WEBHOOK_ID_{chain} configured.")
                continue
            await self._patch_webhook(chain, webhook_id, addresses)

    async def _patch_webhook(self, chain: str, webhook_id: str, addresses: list[str]) -> None:
        endpoint = f"{self.base_url}/update-webhook-addresses"
        headers = {
            "Content-Type": "application/json",
            "X-Alchemy-Token": self.auth_token,
        }
        for start in range(0, len(addresses), 500):
            batch = addresses[start : start + 500]
            payload = {
                "webhook_id": webhook_id,
                "addresses_to_add": batch,
                "addresses_to_remove": [],
            }
            client = HttpClientManager.get_client("alchemy", timeout=30.0)
            response = await client.patch(endpoint, headers=headers, json=payload)
            if response.is_success:
                logger.info(
                    f"{chain}: webhook {webhook_id} added {len(batch)} addresses (HTTP {response.status_code})."
                )
            else:
                logger.error(
                    f"{chain}: webhook {webhook_id} sync failed: HTTP {response.status_code} {response.text}"
                )
                return

    async def sync_webhook_addresses(
        self, webhook_id: str, verified_addresses: list[str]
    ) -> None:
        """Replace the entire list of addresses tracked in a given webhook (legacy).

        Args:
            webhook_id: Alchemy webhook ID (e.g., "wh_...").
            verified_addresses: List of checksummed addresses to track.
        """
        endpoint = f"{self.base_url}/update-webhook-addresses"

        headers = {
            "Content-Type": "application/json",
            "X-Alchemy-Token": self.auth_token,
        }

        payload = {
            "webhook_id": webhook_id,
            "addresses": verified_addresses,
        }

        client = HttpClientManager.get_client("alchemy", timeout=30.0)
        response = await client.put(endpoint, headers=headers, json=payload)

        if response.status_code == 200:
            logger.info(f"Synced {len(verified_addresses)} addresses to webhook {webhook_id}.")
        else:
            logger.error(f"Alchemy sync failed: {response.status_code} - {response.text}")
            response.raise_for_status()
