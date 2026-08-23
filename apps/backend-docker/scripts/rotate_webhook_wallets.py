"""Manually trigger the 300-wallet active rotation cycle.

Reads DB + Alchemy credentials from .env, diffs the top 300 high-conviction
wallets against what Alchemy currently tracks, PATCHes the delta, and
reconciles ``is_monitored_active`` in Postgres.

Run:  poetry run python scripts/rotate_webhook_wallets.py
"""
from __future__ import annotations

import asyncio
import logging

from whaledecode.adapters.db.session import create_session_factory
from whaledecode.config.settings import Settings
from whaledecode.services.webhook_rotator import WebhookRotationService


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings()
    factory = create_session_factory(settings)
    svc = WebhookRotationService(settings, factory)

    if not svc.auth_token or not svc.webhook_id:
        logging.error("Missing Alchemy credentials (ALCHEMY_API_KEY / ALCHEMY_WEBHOOK_ID).")
        return 1

    summary = await svc.sync_rotation_cycle()
    logging.info(
        "Rotation complete: added=%d removed=%d monitored=%d",
        summary["added"],
        summary["removed"],
        summary["monitored"],
    )
    # Verification query target:
    #   SELECT is_monitored_active, count(*) FROM curated_wallets GROUP BY 1;
    print(
        f"\nRotation summary: +{summary['added']} / -{summary['removed']} "
        f"| {summary['monitored']} wallets now is_monitored_active = TRUE"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
