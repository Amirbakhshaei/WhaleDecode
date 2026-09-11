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
from aiolimiter import AsyncLimiter
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from whaledecode.adapters.chain.evm_poller import EvmTargetedPoller
from whaledecode.adapters.chain.poller import TargetedChainPoller, backoff_sleep
from whaledecode.adapters.chain.solana_poller import SolanaTargetedPoller
from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.config.settings import Settings
from whaledecode.domain.policies.sentinel import SentinelEngine
from whaledecode.domain.schemas.ingest import is_valid_ingest_hash

from whaledecode.infrastructure.pipeline_telemetry import (
    log_activities_fetched,
    log_ingest_duplicate,
    log_ingest_evaluated,
    log_ingest_filtered,
    log_ingest_inserted,
    log_poll_start,
    log_rpc_health_snapshot,
)
from whaledecode.infrastructure.rpc_router import RpcFailoverRouter, split_urls
from whaledecode.infrastructure.telemetry import start_trace
from whaledecode.pools.rpc.manager import ResilientRPCManager

log = structlog.get_logger()

# ponytail: belt-and-suspenders exclusion list for firehose contracts. The
# primary gate is ``curated_wallets.is_exchange`` (filtered by ``list_active``)
# plus the FUNDING_ONLY_ADDRESSES set in curation/sources.py; this constant is
# an extra defence in case a sync ever inserts one of these rows with the
# wrong flag. All lower-cased so case mismatches in the seed don't bypass it.
EXCLUDED_POLLING_ADDRESSES: set[str] = {
    "0x28c6c06298d514db089934071355e5743bf21d60",  # Binance 14
    "0x09aea4b2242abc8bb4bb78d537a67a245a7bec64",  # Across Base SpokePool
    "0xe35e9842fceaca96570b734083f4a58e8f7c5f2a",  # Across ARB SpokePool
    "0xce16f69375520ab01377ce7b88f5ba8c48f8d666",  # Axelar Gateway
    "0xf326e4de8f66a0bdc0970b79e0924e33c79f1915",  # MetaMask Fee Collector
}

# chain code (curated_wallets.chain) -> (label, settings key for RPC URLs)
_EVM_CHAINS = {
    "ETH": ("Ethereum", "ETH_PUBLIC_RPC_URLS"),
    "BASE": ("Base", "BASE_PUBLIC_RPC_URLS"),
    "ARB": ("Arbitrum", "ARB_PUBLIC_RPC_URLS"),
}


class TargetedPollerService:
    # ponytail: chain code → ResilientRPCManager chain name mapping.
    _CODE_TO_NAME = {"ETH": "ethereum", "ARB": "arbitrum", "BASE": "base"}

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        rpc_manager: ResilientRPCManager | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._sentinel = SentinelEngine()
        self._shared_manager = rpc_manager
        self._routers: dict[str, RpcFailoverRouter] = {}
        self._pollers: dict[str, TargetedChainPoller] = {}
        # Shared rate limiter for all EVM pollers (10 req/s total)
        self._rate_limiter = AsyncLimiter(max_rate=10, time_period=1.0)
        # If a shared manager is provided, pre-populate routers from it
        # so we don't create duplicate httpx clients.
        if rpc_manager is not None:
            for code, name in self._CODE_TO_NAME.items():
                router = rpc_manager.get_router(name)
                if router is not None:
                    self._routers[code.lower()] = router

    def _poller_for(self, chain_code: str) -> TargetedChainPoller | None:
        if chain_code in self._pollers:
            return self._pollers[chain_code]
        if chain_code == "SOL":
            router = self._router("solana", "SOL_PUBLIC_RPC_URLS")
            poller: TargetedChainPoller | None = SolanaTargetedPoller(router)
        elif chain_code in _EVM_CHAINS:
            label, urls_key = _EVM_CHAINS[chain_code]
            router = self._router(chain_code.lower(), urls_key)
            poller = EvmTargetedPoller(chain_code, label, router, rate_limiter=self._rate_limiter, settings=self._settings)
        else:
            log.warning("targeted_poller_unknown_chain", extra={"chain": chain_code})
            poller = None
        if poller is not None:
            self._pollers[chain_code] = poller
        return poller

    def _router(self, name: str, urls_key: str) -> RpcFailoverRouter:
        if name not in self._routers:
            # Get per-chain cooldown
            cooldown_attr = f"TARGETED_RPC_COOLDOWN_SECONDS_{name.upper()}"
            cooldown = getattr(self._settings, cooldown_attr, self._settings.TARGETED_RPC_COOLDOWN_SECONDS)
            
            # Explicit tier separation: public URLs as primary, dedicated (auth) as fallback for ETH
            public_urls = split_urls(getattr(self._settings, urls_key, ""))
            dedicated_urls = []
            
            # For ETH: use authenticated endpoints as dedicated tier
            if name == "eth" and self._settings.ETH_RPC_URLS:
                dedicated_urls = split_urls(self._settings.ETH_RPC_URLS)
                log.info(
                    "rpc_pool_tiered",
                    extra={
                        "router": name,
                        "public_nodes": len(public_urls),
                        "dedicated_nodes": len(dedicated_urls),
                    },
                )
            
            self._routers[name] = RpcFailoverRouter(
                name,
                public_urls=public_urls,
                dedicated_urls=dedicated_urls,
                cooldown_seconds=cooldown,
            )
            log.info(
                "rpc_pool_loaded",
                extra={
                    "router": name,
                    "public_nodes": len(public_urls),
                    "dedicated_nodes": len(dedicated_urls),
                    "cooldown_seconds": cooldown,
                },
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
        # ponytail: per-cycle trace_id so ETH/BASE/ARB sub-logs share a
        # correlation root. Cheap (uuid4 hex) and survives the asyncio
        # ContextVar copy across awaits.
        start_trace()
        inserted = 0
        async with UnitOfWork(self._session_factory) as uow:
            for code in (*_EVM_CHAINS, "SOL"):
                wallets = await uow.curated_wallets.list_active(chain=code)
                if not wallets:
                    continue
                # Filter the belt-and-suspenders exclusion list. Cheap in-memory
                # scan; the set is <10 entries.
                wallets = [w for w in wallets if w.address.lower() not in EXCLUDED_POLLING_ADDRESSES]
                if not wallets:
                    continue
                # Limit ETH wallets to reduce RPC load on free endpoints
                if code == "ETH" and len(wallets) > self._settings.MAX_ETH_WALLETS_PER_POLL:
                    wallets = wallets[: self._settings.MAX_ETH_WALLETS_PER_POLL]
                # Get RPC endpoints for logging
                router = self._router(code.lower(), _EVM_CHAINS.get(code, ("", ""))[1]) if code in _EVM_CHAINS else self._router("solana", "SOL_PUBLIC_RPC_URLS")
                rpc_endpoints = []
                nodes = []
                try:
                    nodes = router.get_node_stats(code.lower())
                    rpc_endpoints = [n.get("url", "") for n in nodes]
                except Exception:
                    pass
                log_poll_start(code, len(wallets), rpc_endpoints=rpc_endpoints)
                
                # RPC health snapshot (every 10th poll)
                if not hasattr(self, "_poll_counter"):
                    self._poll_counter = 0
                self._poll_counter += 1
                if self._poll_counter % 10 == 0:
                    active_node = None
                    cooldown_count = 0
                    failed_count = 0
                    try:
                        active_node = router.get_active_node(code.lower())
                        cooldown_count = sum(1 for n in nodes if n.get("in_cooldown"))
                        failed_count = sum(1 for n in nodes if n.get("failed"))
                    except Exception:
                        pass
                    log_rpc_health_snapshot(
                        chain=code,
                        nodes=nodes,
                        active_node=active_node,
                        nodes_in_cooldown=cooldown_count,
                        nodes_failed=failed_count,
                    )
                
                poller = self._poller_for(code)
                if poller is None:
                    continue
                # ponytail: jitter defeats WAF rhythm detection —
                # randomise the pre-request pause per chain per cycle.
                await asyncio.sleep(random.uniform(0.5, 3.5))
                try:
                    activities = await poller.fetch_recent_activity(list(wallets))
                except Exception as e:  # noqa: BLE001 - one chain down ≠ all chains down
                    log.error("targeted_poll_failed", extra={"chain": code, "error": str(e)}, exc_info=True)
                    continue
                # Telemetry: log activities fetched per wallet
                for wallet in wallets:
                    wallet_activities = [a for a in activities if a.get("wallet_id") == wallet.id]
                    if wallet_activities:
                        log_activities_fetched(code, wallet.address, len(wallet_activities))
                kept = []
                for a in activities:
                    if not self._passes_gate(a):
                        # Use the same floor calculation as _passes_gate for consistency
                        chain = a.get("chain", code).upper()
                        floor_attr = f"TARGETED_MIN_TX_USD_{chain}"
                        floor_usd = float(getattr(self._settings, floor_attr, self._settings.TARGETED_MIN_TX_USD))
                        log_ingest_filtered(
                            a.get("chain", code),
                            a.get("wallet_address", "unknown"),
                            a.get("tx_hash", "unknown"),
                            "below_usd_floor",
                            float(a.get("value_usd") or 0.0),
                            floor_usd,
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

        Uses per-chain USD floor so an event that passes here will not be
        immediately skipped downstream.  The Sentinel score is also checked —
        a zero-conviction event can never clear the investigation score gate,
        so inserting it only wastes a DB row and a worker claim cycle.
        """
        score = self._sentinel.score(activity)
        activity["score"] = score
        value_usd = float(activity.get("value_usd") or 0.0)
        chain = activity.get("chain", "").upper()
        
        # Per-chain USD floor
        floor_attr = f"TARGETED_MIN_TX_USD_{chain}"
        floor_usd = float(getattr(self._settings, floor_attr, self._settings.TARGETED_MIN_TX_USD))
        gate_passed = value_usd >= floor_usd and score >= self._settings.MIN_INVESTIGATION_SCORE
        # ponytail: one structured line per valuation decision — every input
        # to the multiplication is logged so a missing oracle price or
        # wrong-decimals bug is diagnosable from a single log search.
        raw = activity.get("raw_json") if isinstance(activity.get("raw_json"), dict) else {}
        log_ingest_evaluated(
            chain=activity.get("chain", ""),
            tx_hash=activity.get("tx_hash", ""),
            wallet_address=activity.get("wallet_address", ""),
            token_symbol=raw.get("symbol") or raw.get("asset") or "",
            token_contract=raw.get("address") or raw.get("contract_address") or "",
            raw_amount=raw.get("token_amount") or raw.get("amount") or 0,
            decimals=raw.get("decimals") or 18,
            token_units=float(raw.get("token_amount") or 0.0),
            oracle_price_usd=float(raw.get("price_at_timestamp") or 0.0),
            calculated_value_usd=value_usd,
            floor_usd=floor_usd,
            gate_passed=gate_passed,
        )
        if not gate_passed:
            return False
        return True

    async def aclose(self) -> None:
        for poller in self._pollers.values():
            closer = getattr(poller, "aclose", None)
            if closer is not None:
                await closer()
        # ponytail: only close routers we own — shared manager's routers
        # are closed by the manager's own aclose().
        if self._shared_manager is not None:
            await self._shared_manager.aclose()
        else:
            for router in self._routers.values():
                await router.aclose()
