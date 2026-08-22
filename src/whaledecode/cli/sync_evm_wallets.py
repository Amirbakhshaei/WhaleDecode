"""Universal EVM wallet migration: unify curated wallets across all EVM chains.

EVM addresses are network-agnostic, but curated_wallets currently tags each row
with a single chain. This script reads every 0x address, ensures an active row
exists for ETH / ARB / BASE (INSERT ... ON CONFLICT DO NOTHING), then pushes the
deduplicated list of addresses to all three Alchemy webhooks.

Run:
    python -m whaledecode.cli.sync_evm_wallets
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from whaledecode.adapters.alchemy.webhook_manager import AlchemyWebhookManager
from whaledecode.adapters.curation import is_safe_for_webhook_sync
from whaledecode.adapters.db.models.curated_wallet import CuratedWalletModel
from whaledecode.config.logging import setup_logging
from whaledecode.config.settings import Settings

logger = logging.getLogger(__name__)

_CHAINS = ("ETH", "ARB", "BASE")


def _session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    from whaledecode.adapters.db.session import create_session_factory

    return create_session_factory(settings)


async def _collect_evm_addresses(session: AsyncSession) -> list[dict]:
    """All unique 0x addresses currently tracked in curated_wallets (with their category + score)."""
    result = await session.execute(
        select(
            CuratedWalletModel.address,
            CuratedWalletModel.category,
            CuratedWalletModel.quality_score,
        ).where(CuratedWalletModel.address.like("0x%")).distinct()
    )
    return [
        {"address": address, "category": category, "quality_score": quality_score}
        for address, category, quality_score in result.all()
    ]


async def _ensure_all_chains(session: AsyncSession, addresses: list[str]) -> int:
    """Insert active rows for every (address, chain) pair missing from the table.

    Uses INSERT ... ON CONFLICT DO NOTHING (unique ``uq_address_chain``) so the
    migration is idempotent. Returns the number of rows actually inserted.
    """
    rows = [
        {"address": address, "chain": chain, "is_active": True}
        for address in addresses
        for chain in _CHAINS
    ]
    dialect = session.bind.dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(CuratedWalletModel)
    else:
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        stmt = sqlite_insert(CuratedWalletModel)
    result = await session.execute(
        stmt.values(rows).on_conflict_do_nothing(index_elements=["address", "chain"])
    )
    return result.rowcount or 0


async def _migrate_wallets(settings: Settings) -> list[dict]:
    """Return the EVM wallet rows, ensured present on all three chains."""
    factory = _session_factory(settings)
    async with factory() as session:
        wallets = await _collect_evm_addresses(session)
        if not wallets:
            logger.warning("No 0x curated wallets found; nothing to migrate.")
            return []
        inserted = await _ensure_all_chains(session, [w["address"] for w in wallets])
        await session.commit()
        logger.info(f"Found {len(wallets)} unique EVM addresses; inserted {inserted} missing (address, chain) rows.")
    return wallets


def _safe_webhook_addresses(wallets: list[dict]) -> list[str]:
    """Filter wallets to the high-conviction, low-frequency subset safe for webhook sync."""
    safe = [w["address"] for w in wallets if is_safe_for_webhook_sync(w)]
    dropped = len(wallets) - len(safe)
    if dropped:
        logger.warning(
            "sync_evm_wallets_safeguard_dropped",
            extra={"dropped": dropped, "kept": len(safe)},
        )
    return safe


async def _run() -> int:
    settings = Settings()
    setup_logging(settings)

    wallets = await _migrate_wallets(settings)
    if not wallets:
        return 0

    safe_addresses = _safe_webhook_addresses(wallets)

    manager = AlchemyWebhookManager.from_settings(settings)
    await manager.sync_addresses(safe_addresses)
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
