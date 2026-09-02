"""Targeted Failover Poller orchestration.

Runs the poller array as a non-blocking asyncio task: adapters fetch targeted
activity over free public RPCs, this service scores and gates it (same
Sentinel threshold as the webhook path) and pipes survivors into
``candidate_events`` for the downstream Edge Intelligence worker.

Chain-agnostic by construction: this file knows nothing about eth_getLogs or
getSignaturesForAddress — only about the TargetedChainPoller interface.
"""
import asyncio
import random
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from whaledecode.adapters.chain.evm_poller import EvmTargetedPoller
from whaledecode.adapters.chain.poller import TargetedChainPoller, backoff_sleep
from whaledecode.adapters.chain.solana_poller import SolanaTargetedPoller
from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.config.settings import Settings
from whaledecode.domain.policies.sentinel import SentinelEngine
from whaledecode.domain.schemas.ingest import is_valid_ingest_hash
from whaledecode.domain.services.event_gate import MIN_WHALE_THRESHOLD_USD
from whaledecode.infrastructure.pipeline_telemetry import (
    log_activities_fetched,
    log_ingest_filtered,
    log_ingest_inserted,
    log_ingest_duplicate,
    log_poll_start,
    set_correlation_id,
)
from whaledecode.infrastructure.rpc_router import RpcFailoverRouter, split_urls

log = structlog.get_logger()

# chain code (curated_wallets.chain) -> (label, settings key for RPC URLs)
_EVM_CHAINS = {
    "ETH": ("Ethereum", "ETH_PUBLIC_RPC_URLS"),
    "BASE": ("Base", "BASE_PUBLIC_RPC_URLS"),
    "ARB": ("Arbitrum", "ARB_PUBLIC_RPC_URLS"),
}


class TargetedPollerService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._sentinel = SentinelEngine()
        self._routers: dict[str, RpcFailoverRouter] = {}
        self._pollers: dict[str, TargetedChainPoller] = {}

    def _poller_for(self, chain_code: str) -> TargetedChainPoller | None:
        if chain_code in self._pollers:
            return self._pollers[chain_code]
        if chain_code == "SOL":
            router = self._router("solana", "SOL_PUBLIC_RPC_URLS")
            poller: TargetedChainPoller | None = SolanaTargetedPoller(router)
        elif chain_code in _EVM_CHAINS:
            label, urls_key = _EVM_CHAINS[chain_code]
            router = self._router(chain_code.lower(), urls_key)
            poller = EvmTargetedPoller(chain_code, label, router)
        else:
            log.warning("targeted_poller_unknown_chain", extra={"chain": chain_code})
            poller = None
        if poller is not None:
            self._pollers[chain_code] = poller
        return poller

    def _router(self, name: str, urls_key: str) -> RpcFailoverRouter:
        if name not in self._routers:
            self._routers[name] = RpcFailoverRouter(
                name,
                split_urls(getattr(self._settings, urls_key, "")),
                cooldown_seconds=self._settings.TARGETED_RPC_COOLDOWN_SECONDS,
            )
        return self._routers[name]

    async def run(self, stop_event: asyncio.Event | None = None) -> None:
        """Never-crash background loop; backs off on total failure."""
        while not (stop_event and stop_event.is_set()):
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - the loop must survive anything
                log.error("targeted_poller_loop_error", extra={"error": str(e)}, exc_info=True)
            await backoff_sleep(self._settings.POLL_INTERVAL_SECONDS, stop_event)

    async def poll_once(self) -> int:
        """One pass across all chains; returns number of pending events inserted."""
        inserted = 0
        async with UnitOfWork(self._session_factory) as uow:
            for code in (*_EVM_CHAINS, "SOL"):
                wallets = await uow.curated_wallets.list_active(chain=code)
                if not wallets:
                    continue
                log_poll_start(code, len(wallets))
                poller = self._poller_for(code)
                if poller is None:
                    continue
                # ponytail: jitter defeats WAF rhythm detection —
                # randomise the pre-request pause per chain per cycle.
                await asyncio.sleep(random.uniform(0.5, 3.5))
                try:
                    activities = await poller.fetch_recent_activity(list(wallets))
                except Exception as e:  # noqa: BLE001 - one chain down ≠ all chains down
                    log.error("targeted_poll_failed", extra={"chain": code, "error": str(e)})
                    continue
                # Telemetry: log activities fetched per wallet
                for wallet in wallets:
                    wallet_activities = [a for a in activities if a.get("wallet_id") == wallet.id]
                    if wallet_activities:
                        log_activities_fetched(code, wallet.address, len(wallet_activities))
                kept = []
                for a in activities:
                    if not self._passes_gate(a):
                        log_ingest_filtered(
                            a.get("chain", code),
                            a.get("wallet_address", "unknown"),
                            a.get("tx_hash", "unknown"),
                            "below_usd_floor",
                            float(a.get("value_usd") or 0.0),
                            MIN_WHALE_THRESHOLD_USD,
                        )
                        continue
                    if not is_valid_ingest_hash(a["tx_hash"], a["chain"]):
                        log_ingest_filtered(
                            a.get("chain", code),
                            a.get("wallet_address", "unknown"),
                            a.get("tx_hash", "unknown"),
                            "invalid_hash",
                            float(a.get("value_usd") or 0.0),
                            0.0,
                        )
                        continue
                    kept.append(a)
                # Insert with telemetry on duplicates
                try:
                    inserted_count = await uow.candidate_events.create_pending_bulk(kept)
                except Exception:
                    inserted_count = 0
                inserted += inserted_count
                if inserted_count:
                    sample_keys = [k["dedupe_key"] for k in kept[:5]]
                    log_ingest_inserted(code, inserted_count, sample_dedupe_keys=sample_keys)
                # Log duplicates (activities not inserted due to ON CONFLICT)
                for a in kept:
                    # Note: create_pending_bulk doesn't return which were skipped, so we log at debug
                    log_ingest_duplicate(
                        a.get("chain", code),
                        a.get("wallet_address", "unknown"),
                        a.get("tx_hash", "unknown"),
                        a.get("log_index", 0),
                    )
            await uow.commit()
        return inserted

    def _passes_gate(self, activity: dict[str, Any]) -> bool:
        """Unified pre-INSERT gate: mirrors the investigation worker's checks.

        Uses MIN_WHALE_THRESHOLD_USD (the same floor ``EventGate`` enforces
        after oracle re-pricing) so an event that passes here will not be
        immediately skipped downstream.  The Sentinel score is also checked —
        a zero-conviction event can never clear the investigation score gate,
        so inserting it only wastes a DB row and a worker claim cycle.
        """
        score = self._sentinel.score(activity)
        activity["score"] = score
        value_usd = float(activity.get("value_usd") or 0.0)
        if value_usd < MIN_WHALE_THRESHOLD_USD:
            return False
        if score < self._settings.MIN_INVESTIGATION_SCORE * 100:
            return False
        return True

    async def aclose(self) -> None:
        for poller in self._pollers.values():
            closer = getattr(poller, "aclose", None)
            if closer is not None:
                await closer()
        for router in self._routers.values():
            await router.aclose()
