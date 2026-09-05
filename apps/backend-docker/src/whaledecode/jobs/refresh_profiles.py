"""Nightly behavioral-profile refresh & funding-edge maintenance (Module 1 & 2 ledger maintenance)."""
import asyncio
from datetime import UTC, datetime, timedelta

import structlog

log = structlog.get_logger()

_REFRESH_CONCURRENCY = 5
_REFRESH_DELAY_SECONDS = 0.2  # pace price-oracle calls across the batch
_FUNDING_EDGE_RETENTION_DAYS = 7


async def refresh_wallet_profiles(session_factory, settings) -> int:
    """Recompute profiles for every active curated wallet. Returns count refreshed."""
    from whaledecode.adapters.db.uow import UnitOfWork
    from whaledecode.adapters.pricing.oracle import PriceOracle
    from whaledecode.adapters.zerion.client import ZerionClient
    from whaledecode.services.behavioral_profiler import BehavioralProfiler

    async with UnitOfWork(session_factory) as uow:
        wallets = await uow.curated_wallets.list_active()
    zerion = ZerionClient.from_settings(settings)
    profiler = BehavioralProfiler(
        lambda: UnitOfWork(session_factory), PriceOracle(), zerion
    )
    semaphore = asyncio.Semaphore(_REFRESH_CONCURRENCY)

    async def _one(chain: str, address: str) -> None:
        async with semaphore:
            try:
                await profiler.refresh_profile(chain, address)
            except Exception as exc:
                log.warning("profile_refresh_failed", wallet=address, error=str(exc))
            await asyncio.sleep(_REFRESH_DELAY_SECONDS)

    await asyncio.gather(*(_one(w.chain, w.address) for w in wallets))
    log.info("wallet_profiles_refreshed", count=len(wallets))
    return len(wallets)


async def prune_funding_edges(session_factory) -> int:
    """Delete funding_edge rows older than _FUNDING_EDGE_RETENTION_DAYS.

    Keeps the graph lean; old edges are noise for current syndicate detection.
    Returns count of deleted rows.
    """
    from sqlalchemy import delete

    from whaledecode.adapters.db.models.funding_edge import FundingEdgeModel
    from whaledecode.adapters.db.uow import UnitOfWork

    cutoff = datetime.now(UTC) - timedelta(days=_FUNDING_EDGE_RETENTION_DAYS)
    async with UnitOfWork(session_factory) as uow:
        result = await uow.session.execute(
            delete(FundingEdgeModel).where(FundingEdgeModel.created_at < cutoff)
        )
        await uow.commit()
    deleted = result.rowcount
    log.info("funding_edges_pruned", deleted=deleted, cutoff=cutoff.isoformat())
    return deleted


async def recalculate_win_rates(session_factory) -> int:
    """Recalculate rolling 30-day win-rates for all tracked cluster wallets.

    Win-rate = profitable accumulations / total tracked accumulations in 30d window.
    Updates wallet_profiles.historical_win_rate_30d.
    Returns count of updated profiles.
    """
    from sqlalchemy import and_, select

    from whaledecode.adapters.db.models.candidate_event import CandidateEventModel
    from whaledecode.adapters.db.models.syndicate_cluster import SyndicateClusterModel
    from whaledecode.adapters.db.models.wallet_profile import WalletProfileModel
    from whaledecode.adapters.db.uow import UnitOfWork

    window_start = datetime.now(UTC) - timedelta(days=30)
    updated = 0

    async with UnitOfWork(session_factory) as uow:
        # Get all wallets that are part of recent syndicates
        clusters = await uow.session.execute(
            select(SyndicateClusterModel).where(SyndicateClusterModel.window_end >= window_start)
        )
        clusters = list(clusters.scalars())

        # Update win rates for all profiles based on candidate events
        profiles = await uow.session.execute(select(WalletProfileModel))
        profiles = list(profiles.scalars())

        for profile in profiles:
            # Count profitable vs total events in 30d window
            events = await uow.session.execute(
                select(CandidateEventModel).where(
                    and_(
                        CandidateEventModel.chain == profile.chain,
                        CandidateEventModel.wallet_address == profile.address,
                        CandidateEventModel.timestamp >= window_start,
                        CandidateEventModel.status.in_(["confirmed", "skipped"]),
                    )
                )
            )
            events = list(events.scalars())

            if events:
                profitable = sum(1 for e in events if (e.realized_pnl_usd or 0) > 0)
                total = len(events)
                win_rate = profitable / total if total > 0 else 0.0
                profile.historical_win_rate_30d = win_rate
                profile.sample_size_30d = total
                updated += 1

        await uow.commit()

    log.info("win_rates_recalculated", updated=updated, window_days=30)
    return updated


async def run_full_refresh(session_factory, settings) -> dict[str, int]:
    """Run all nightly maintenance tasks. Returns dict with counts."""
    profiles = await refresh_wallet_profiles(session_factory, settings)
    pruned = await prune_funding_edges(session_factory)
    win_rates = await recalculate_win_rates(session_factory)
    return {
        "profiles_refreshed": profiles,
        "edges_pruned": pruned,
        "win_rates_updated": win_rates,
    }
