"""Nightly behavioral-profile refresh (Module 1 ledger maintenance)."""
import asyncio

import structlog

log = structlog.get_logger()

_REFRESH_CONCURRENCY = 5
_REFRESH_DELAY_SECONDS = 0.2  # pace price-oracle calls across the batch


async def refresh_wallet_profiles(session_factory, settings) -> int:
    """Recompute profiles for every active curated wallet. Returns count refreshed."""
    from whaledecode.adapters.arkham.client import ArkhamClient
    from whaledecode.adapters.db.uow import UnitOfWork
    from whaledecode.adapters.pricing.oracle import PriceOracle
    from whaledecode.services.behavioral_profiler import BehavioralProfiler

    async with UnitOfWork(session_factory) as uow:
        wallets = await uow.curated_wallets.list_active()
    arkham = ArkhamClient(settings.ARKHAM_API_KEY.get_secret_value() if settings.ARKHAM_API_KEY else "")
    profiler = BehavioralProfiler(
        lambda: UnitOfWork(session_factory), PriceOracle(), arkham
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
