"""Alchemy Notify API webhook management."""
import logging

import httpx

logger = logging.getLogger(__name__)


class AlchemyWebhookManager:
    def __init__(self, alchemy_auth_token: str) -> None:
        """
        Args:
            alchemy_auth_token: Notify API Auth Token (Dashboard -> Data -> Webhooks -> Auth Token).
        """
        self.auth_token = alchemy_auth_token
        self.base_url = "https://dashboard.alchemy.com/api"

    async def sync_webhook_addresses(
        self, webhook_id: str, verified_addresses: list[str]
    ) -> None:
        """
        Replace the entire list of addresses tracked in a given webhook.

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

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.put(endpoint, headers=headers, json=payload)

            if response.status_code == 200:
                logger.info(f"Synced {len(verified_addresses)} addresses to webhook {webhook_id}.")
            else:
                logger.error(f"Alchemy sync failed: {response.status_code} - {response.text}")
                response.raise_for_status()

