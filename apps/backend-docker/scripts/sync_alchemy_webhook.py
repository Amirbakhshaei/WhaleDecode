"""Programmatic Alchemy Notify webhook sync for extracted trigger wallets.

Reads ``data/alchemy_webhook_wallets.json`` (produced by
``extract_active_wallets.py``) and synchronizes the tracked address set with a
single Alchemy webhook via PATCH ``update-webhook-addresses`` — adding new
trigger wallets and removing any address no longer in the high-conviction set.

Run:  poetry run python scripts/sync_alchemy_webhook.py
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from whaledecode.config.settings import Settings
from whaledecode.infrastructure.http import HttpClientManager

logger = logging.getLogger(__name__)

_INPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "alchemy_webhook_wallets.json"
_ENDPOINT = "https://dashboard.alchemy.com/api/update-webhook-addresses"
_BATCH = 500
_MAX_BACKOFF = 30.0


def _auth_token(settings: Settings) -> str:
    token = settings.ALCHEMY_API_KEY or settings.ALCHEMY_NOTIFY_TOKEN or settings.ALCHEMY_AUTH_TOKEN
    return token.get_secret_value() if token else ""


def _webhook_id(settings: Settings) -> str:
    return settings.ALCHEMY_WEBHOOK_ID or settings.ALCHEMY_WEBHOOK_ID_ETH


def _load_addresses(path: Path) -> list[str]:
    with open(path) as f:
        wallets = json.load(f)
    # Dedup + lowercase; Alchemy stores addresses normalized to lower-case.
    return sorted({w["address"].lower().strip() for w in wallets if w.get("address")})


async def _patch(client, headers: dict, webhook_id: str, add: list[str], remove: list[str]) -> None:
    payload = {"webhook_id": webhook_id, "addresses_to_add": add, "addresses_to_remove": remove}
    backoff = 1.0
    while True:
        resp = await client.patch(_ENDPOINT, headers=headers, json=payload)
        if resp.status_code == 429 or resp.status_code >= 500:
            logger.warning("Alchemy throttled (%s); backing off %ss", resp.status_code, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _MAX_BACKOFF)
            continue
        if not resp.is_success:
            # Surface a sample; do not retry client errors (4xx) — they need a fix.
            raise RuntimeError(f"Alchemy sync failed HTTP {resp.status_code}: {resp.text[:500]}")
        return


async def sync(webhook_id: str, addresses: list[str], current: list[str] | None = None) -> tuple[int, int]:
    """Diff ``addresses`` against ``current`` (fetched when None) and PATCH in <=500 batches."""
    settings = Settings()
    token = _auth_token(settings)
    if not token:
        raise RuntimeError("No Alchemy auth token set (ALCHEMY_API_KEY / ALCHEMY_NOTIFY_TOKEN / ALCHEMY_AUTH_TOKEN).")
    if not webhook_id:
        raise RuntimeError("No Alchemy webhook id set (ALCHEMY_WEBHOOK_ID / ALCHEMY_WEBHOOK_ID_ETH).")

    headers = {"X-Alchemy-Token": token, "Content-Type": "application/json"}
    client = HttpClientManager.get_client("alchemy", timeout=30.0)

    if current is None:
        current = await _fetch_current(client, token, webhook_id)

    want = set(addresses)
    current_set = {a.lower() for a in current}
    to_add = sorted(want - current_set)
    to_remove = sorted(current_set - want)
    logger.info("Sync plan: +%d / -%d (webhook currently holds %d)", len(to_add), len(to_remove), len(current_set))

    for chunk in range(0, max(len(to_add), 1), _BATCH):
        add_batch = to_add[chunk : chunk + _BATCH]
        remove_batch = to_remove[chunk : chunk + _BATCH] if chunk < len(to_remove) else []
        await _patch(client, headers, webhook_id, add_batch, remove_batch)
        logger.info("Patched batch +%d / -%d", len(add_batch), len(remove_batch))
    return len(to_add), len(to_remove)


async def _fetch_current(client, token: str, webhook_id: str) -> list[str]:
    addresses: list[str] = []
    url = "https://dashboard.alchemy.com/api/webhook-addresses"
    next_page: str | None = url
    headers = {"X-Alchemy-Token": token}
    while next_page:
        resp = await client.get(next_page, headers=headers, params={"webhook_id": webhook_id})
        if not resp.is_success:
            logger.error("list addresses failed HTTP %s: %s", resp.status_code, resp.text[:300])
            break
        data = resp.json()
        addresses.extend(data.get("data", []))
        next_page = (data.get("pagination") or {}).get("next")
    return [a.lower().strip() for a in addresses if a]


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not _INPUT_PATH.exists():
        logger.error("Input file %s not found. Run extract_active_wallets.py first.", _INPUT_PATH)
        return 1
    settings = Settings()
    webhook_id = _webhook_id(settings)
    addresses = _load_addresses(_INPUT_PATH)
    logger.info("Loaded %d unique trigger addresses from %s", len(addresses), _INPUT_PATH)
    added, removed = await sync(webhook_id, addresses)
    logger.info("Sync complete: added %d, removed %d", added, removed)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
