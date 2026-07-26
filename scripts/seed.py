"""Seed database with curated wallets and demo events.

Run via: whaledecode seed
"""

import json
from pathlib import Path

import structlog
from whaledecode.config.settings import Settings

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


async def run_seed(settings: Settings) -> None:
    log = structlog.get_logger()

    wallets_path = DATA_DIR / "wallets_seed.json"
    events_path = DATA_DIR / "events_seed.json"

    if not wallets_path.exists():
        log.warning("wallets_seed.json not found, skipping")
        return

    with open(wallets_path) as f:
        wallets = json.load(f)
    log.info("loaded_wallets", count=len(wallets))

    if events_path.exists():
        with open(events_path) as f:
            events = json.load(f)
        log.info("loaded_events", count=len(events))

    # Phase 1: will persist to database via repositories
    log.info("seed_complete")
