"""Prune toxic / high-frequency addresses from configured Alchemy webhooks.

Identifies blacklisted addresses (token contracts, DEX routers, CEX hot
sweepers) currently registered on the per-chain webhooks and removes them via
the Notify API's ``update-webhook-addresses`` PATCH.

Run directly:   python -m whaledecode.cli.prune_alchemy_webhooks
Or via CLI:     whaledecode prune-alchemy-webhooks
"""
from __future__ import annotations

import asyncio
import logging

from whaledecode.adapters.alchemy.webhook_manager import AlchemyWebhookManager
from whaledecode.adapters.curation.sources import DISALLOWED_WEBHOOK_ADDRESSES
from whaledecode.config.logging import setup_logging
from whaledecode.config.settings import Settings

# Re-exported for the existing test / ad-hoc callers. The canonical set lives in
# ``adapters.curation.sources`` so the pruner and the sync gate never diverge.
BLACKLISTED_ADDRESSES = DISALLOWED_WEBHOOK_ADDRESSES

log = logging.getLogger(__name__)


async def run_pruner() -> int:
    settings = Settings()
    setup_logging(settings)

    manager = AlchemyWebhookManager.from_settings(settings)
    if not manager.auth_token:
        log.error("prune_no_token", extra={"hint": "ALCHEMY_NOTIFY_TOKEN / ALCHEMY_AUTH_TOKEN not set"})
        return 1

    removed_total = 0
    for chain, webhook_id in manager.webhook_ids.items():
        if not webhook_id:
            log.warning("prune_skip_chain", extra={"chain": chain, "hint": "no ALCHEMY_WEBHOOK_ID configured"})
            continue

        registered = await manager.list_addresses(webhook_id)
        log.info(
            "prune_listed",
            extra={"chain": chain, "webhook_id": webhook_id, "registered": len(registered)},
        )
        flagged = sorted(set(registered) & BLACKLISTED_ADDRESSES)
        if not flagged:
            log.info("prune_clean", extra={"chain": chain})
            continue

        log.warning(
            "prune_flagged",
            extra={"chain": chain, "count": len(flagged), "addresses": flagged},
        )
        if await manager.remove_addresses(webhook_id, flagged):
            removed_total += len(flagged)

    log.info("prune_done", extra={"removed": removed_total})
    return 0


def main() -> int:
    return asyncio.run(run_pruner())


if __name__ == "__main__":
    raise SystemExit(main())
