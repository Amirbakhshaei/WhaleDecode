"""Sync curated entities (Dune baseline + DefiLlama) into Postgres + Alchemy webhooks.

Reconciled to the real codebase APIs:
* ``Settings()`` (not a ``settings`` singleton)
* ``create_session_factory(settings)`` (not ``async_session_factory``)
* ``CuratedWalletModel`` (the SQLAlchemy model; ``CuratedWallet`` is the pydantic entity)
* ``AlchemyWebhookManager.from_settings(settings).sync_addresses(...)``

Run directly:  python -m whaledecode.cli.sync_curated_entities
Or via CLI:    whaledecode sync-curated
"""
from __future__ import annotations

import asyncio
import logging

import click
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from whaledecode.adapters.alchemy.webhook_manager import AlchemyWebhookManager
from whaledecode.adapters.curation import DefiLlamaAdapter, DuneSpellbookAdapter
from whaledecode.adapters.db.models.curated_wallet import CuratedWalletModel
from whaledecode.adapters.db.session import create_session_factory
from whaledecode.config.logging import setup_logging
from whaledecode.config.settings import Settings

log = logging.getLogger(__name__)


def _to_row(seed) -> dict:
    return {
        "address": seed.address,
        "chain": seed.chain,
        "network_family": seed.network_family,
        "label": seed.label,
        "category": seed.category,
        "tags": ",".join(seed.tags),
        "quality_score": seed.quality_score,
        "is_active": True,
    }


async def run_sync_pipeline() -> None:
    settings = Settings()
    settings.inject_langsmith_env()
    setup_logging(settings)
    session_factory = create_session_factory(settings)

    dune = DuneSpellbookAdapter()
    llama = DefiLlamaAdapter()

    seeds = await dune.fetch() + await llama.fetch()

    # Validate + dedupe by (address, chain).
    seen: set[tuple[str, str]] = set()
    valid: list[dict] = []
    for seed in seeds:
        try:
            from whaledecode.adapters.curation import validate_seed

            validate_seed(seed)
        except ValueError as exc:
            log.warning("skip_invalid_seed", extra={"error": str(exc)})
            continue
        key = (seed.address.lower(), seed.chain)
        if key in seen:
            continue
        seen.add(key)
        valid.append(_to_row(seed))

    if not valid:
        log.warning("sync_no_seeds", extra={"hint": "Dune baseline should always yield rows; check imports"})
        return

    evm_addresses = [
        row["address"] for row in valid if row["network_family"] == "EVM"
    ]

    async with session_factory() as session:
        stmt = pg_insert(CuratedWalletModel).values(valid)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_curated_address_chain",
            set_={
                "label": stmt.excluded.label,
                "category": stmt.excluded.category,
                "tags": stmt.excluded.tags,
                "quality_score": stmt.excluded.quality_score,
                "is_active": stmt.excluded.is_active,
                "updated_at": func.now(),
            },
        )
        await session.execute(stmt)
        await session.commit()

        result = await session.execute(
            select(CuratedWalletModel.network_family, func.count()).group_by(
                CuratedWalletModel.network_family
            )
        )
        summary = {fam: cnt for fam, cnt in result.all()}

    log.info(
        "sync_done",
        extra={
            "inserted": len(valid),
            "evm_addresses": len(evm_addresses),
            "by_family": summary,
        },
    )

    # Solana summary (currently informational; wire a Helius/SVM webhook here later).
    solana = [row for row in valid if row["network_family"] == "SVM"]
    if solana:
        log.info("solana_curated", extra={"count": len(solana), "note": "no Alchemy webhook for SVM yet"})

    if evm_addresses:
        try:
            manager = AlchemyWebhookManager.from_settings(settings)
            await manager.sync_addresses(evm_addresses)
        except Exception as exc:  # noqa: BLE001 - webhook sync must not fail the pipeline
            log.error("alchemy_webhook_sync_failed", extra={"error": str(exc)})


@click.command(name="sync-curated")
def sync_curated_command() -> None:
    """Sync curated entities (Dune baseline + DefiLlama) into Postgres + Alchemy."""
    asyncio.run(run_sync_pipeline())


if __name__ == "__main__":
    asyncio.run(run_sync_pipeline())
