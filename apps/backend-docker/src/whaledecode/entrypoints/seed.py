"""Seed database with curated wallets.

Run via: whaledecode seed
"""

import json
from pathlib import Path

import structlog
from whaledecode.adapters.db.session import create_session_factory
from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.config.settings import Settings
from whaledecode.domain.entities.curated_wallet import CuratedWallet
from whaledecode.domain.value_objects.chain import Chain

_CHAIN_FROM_STR: dict[str, Chain] = {
    "ETH": Chain.ETH,
    "BASE": Chain.BASE,
    "ARB": Chain.ARB,
}


def _find_data_dir() -> Path:
    path = Path(__file__).resolve()
    for parent in path.parents:
        candidate = parent / "data"
        if candidate.is_dir():
            return candidate
    return path.parent / "data"


async def ensure_curated_wallets_seeded(session_factory) -> None:
    wallets_path = _find_data_dir() / "wallets_seed.json"
    if not wallets_path.exists():
        return

    existing_count = 0
    async with UnitOfWork(session_factory) as uow:
        existing = await uow.curated_wallets.list_active()
        existing_count = len(existing)
    if existing_count > 0:
        return

    with open(wallets_path) as f:
        wallets_data = json.load(f)
    for w in wallets_data:
        chain = _CHAIN_FROM_STR.get(w["chain"])
        if chain is None:
            continue
        wallet = CuratedWallet(
            address=w["address"],
            chain=chain,
            label=w.get("label", ""),
            tags=w.get("tags", []),
            quality_score=w.get("quality_score", 0.5),
            is_active=True,
        )
        async with UnitOfWork(session_factory) as uow:
            existing = await uow.curated_wallets.get_by_address_and_chain(wallet.address, wallet.chain.name)
            if existing:
                continue
            await uow.curated_wallets.create(wallet)
            await uow.commit()


async def run_seed(settings: Settings) -> None:
    log = structlog.get_logger()

    wallets_path = _find_data_dir() / "wallets_seed.json"
    if not wallets_path.exists():
        log.warning("wallets_seed.json not found", path=str(wallets_path))
        return

    with open(wallets_path) as f:
        wallets_data = json.load(f)
    log.info("loaded_wallets", count=len(wallets_data))

    session_factory = create_session_factory(settings)
    created = 0
    skipped = 0
    for w in wallets_data:
        chain = _CHAIN_FROM_STR.get(w["chain"])
        if chain is None:
            log.warning("unknown_chain", chain=w["chain"], address=w["address"])
            continue
        wallet = CuratedWallet(
            address=w["address"],
            chain=chain,
            label=w.get("label", ""),
            tags=w.get("tags", []),
            quality_score=w.get("quality_score", 0.5),
            is_active=True,
        )
        async with UnitOfWork(session_factory) as uow:
            existing = await uow.curated_wallets.get_by_address_and_chain(wallet.address, wallet.chain.name)
            if existing:
                skipped += 1
                continue
            await uow.curated_wallets.create(wallet)
            await uow.commit()
            created += 1

    log.info("seed_complete", created=created, skipped=skipped)
