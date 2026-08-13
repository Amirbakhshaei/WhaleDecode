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
from whaledecode.adapters.db.models.curated_wallet import CuratedWalletModel
from whaledecode.config.logging import setup_logging
from whaledecode.config.settings import Settings

logger = logging.getLogger(__name__)

_CHAINS = ("ETH", "ARB", "BASE")


def _session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    from whaledecode.adapters.db.session import create_session_factory

    return create_session_factory(settings)


async def _collect_evm_addresses(session: AsyncSession) -> list[str]:
    """All unique 0x addresses currently tracked in curated_wallets."""
    result = await session.execute(
        select(CuratedWalletModel.address).where(CuratedWalletModel.address.like("0x%")).distinct()
    )
    return sorted(address for (address,) in result.all())


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


async def _migrate_wallets(settings: Settings) -> list[str]:
    """Return the deduplicated EVM address list, ensured present on all three chains."""
    factory = _session_factory(settings)
    async with factory() as session:
        addresses = await _collect_evm_addresses(session)
        if not addresses:
            logger.warning("No 0x curated wallets found; nothing to migrate.")
            return []
        inserted = await _ensure_all_chains(session, addresses)
        await session.commit()
        logger.info(f"Found {len(addresses)} unique EVM addresses; inserted {inserted} missing (address, chain) rows.")
    return addresses


async def _run() -> int:
    settings = Settings()
    setup_logging(settings)

    addresses = await _migrate_wallets(settings)
    if not addresses:
        return 0

    manager = AlchemyWebhookManager.from_settings(settings)
    await manager.sync_addresses(addresses)
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
