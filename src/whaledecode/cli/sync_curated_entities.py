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
from whaledecode.adapters.curation import (
    DefiLlamaAdapter,
    DuneSpellbookAdapter,
    is_webhook_eligible,
)
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

    # Static Dune baseline is always present (zero keys, never fails).
    dune_static = DuneSpellbookAdapter()
    seeds: list = list(await dune_static.fetch())

    # Live Dune API is primary when a key is configured; on free-tier exhaustion
    # it returns [] and we silently keep the static seed (auto-resumes next run).
    api_key = settings.DUNE_API_KEY.get_secret_value() if settings.DUNE_API_KEY else None
    if api_key:
        from whaledecode.adapters.curation import DuneApiAdapter

        live = await DuneApiAdapter(api_key=api_key).fetch()
        if live:
            log.info("dune_live_used", extra={"count": len(live)})
            seeds += live  # appended after static -> wins on upsert conflict
        else:
            log.warning("dune_live_fallback", extra={"hint": "using static Dune seed"})

    llama = DefiLlamaAdapter()
    seeds += await llama.fetch()

    # Validate + dedupe by (address, chain).
    seen: set[tuple[str, str]] = set()
    valid: list[dict] = []
    webhook_eligible_rows: list[dict] = []
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
        row = _to_row(seed)
        valid.append(row)
        # Only high-conviction, low-frequency seeds go to the Alchemy webhook;
        # the rest stay in Postgres (for wallet lookups) but are never tracked.
        if is_webhook_eligible(seed):
            webhook_eligible_rows.append(row)

    if not valid:
        log.warning("sync_no_seeds", extra={"hint": "Dune baseline should always yield rows; check imports"})
        return

    evm_addresses = [
        row["address"] for row in webhook_eligible_rows if row["network_family"] == "EVM"
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
