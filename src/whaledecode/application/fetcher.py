"""Producer: live blockchain fetcher.

Polls RPC nodes, decodes logs, and queues ``pending`` candidate_events for the
consumer worker. This module is deliberately I/O bound to the chain provider and
the database only — it must not import or call the investigation service or any
LangChain/LLM component.
"""
import asyncio
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from whaledecode.adapters.chain.factory import create_chain_provider
from whaledecode.adapters.chain.normalizer import normalize_log
from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.config.settings import Settings
from whaledecode.domain.policies.sentinel import SentinelEngine

log = structlog.get_logger()

DEFAULT_MAX_GET_LOGS_BLOCK_RANGE = 5


def bounded_from_block(from_block: int, to_block: int, max_block_range: int) -> int:
    """Clamp from_block so the requested range never exceeds max_block_range."""
    if to_block - from_block > max_block_range:
        return to_block - max_block_range
    return from_block


def max_block_range_for(chain: str, ranges: dict[str, int]) -> int:
    """Per-chain eth_getLogs range limit, falling back to a safe default."""
    return ranges.get(chain, DEFAULT_MAX_GET_LOGS_BLOCK_RANGE)


class LiveBlockchainFetcher:
    """Polls RPC nodes and inserts high-conviction events as ``pending``."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._provider = create_chain_provider(settings)
        self._sentinel = SentinelEngine()

    async def run(self, stop_event: asyncio.Event | None = None) -> None:
        """Main loop: never crashes silently, backs off with a sleep on failure."""
        while not (stop_event and stop_event.is_set()):
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("fetcher_loop_error", error=str(e), exc_info=True)
            try:
                await asyncio.sleep(self._settings.POLL_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                raise

    async def poll_once(self) -> None:
        """One fetch pass: wallets → head block → logs → pending inserts."""
        async with UnitOfWork(self._session_factory) as uow:
            wallets = await uow.curated_wallets.list_active()

        if not wallets:
            log.info("fetcher_no_wallets")
            return

        chains = {w.chain.label() for w in wallets}
        for chain in chains:
            try:
                block = await self._provider.get_block_number(chain)
            except Exception as e:
                log.error("fetcher_block_failed", chain=chain, error=str(e))
                continue

            on_chain = [w for w in wallets if w.chain.label() == chain]
            addresses = [w.address for w in on_chain]
            addr_map = {w.address: w.id for w in on_chain}

            for i in range(0, len(addresses), self._settings.POLL_BATCH_SIZE):
                batch = addresses[i : i + self._settings.POLL_BATCH_SIZE]
                from_block = self._from_block(chain, block)
                try:
                    logs = await self._provider.get_logs(
                        chain=chain,
                        addresses=batch,
                        from_block=from_block,
                        to_block=block,
                        topics=[],
                    )
                except Exception as e:
                    log.error("fetcher_logs_failed", chain=chain, batch=i, error=str(e))
                    continue

                pending = [
                    self._to_pending_data(event)
                    for raw_log in logs
                    if (wallet_id := addr_map.get(raw_log.get("address", ""))) is not None
                    for event in [normalize_log(raw_log, wallet_id, chain)]
                    if self._above_threshold(event)
                ]
                if pending:
                    await self._insert_pending(pending)
                    log.info("fetcher_inserted", chain=chain, count=len(pending))

        log.info("fetcher_poll_complete", wallet_count=len(wallets))

    def _from_block(self, chain: str, block: int) -> int:
        requested = block - self._settings.REORG_SAFE_BLOCKS
        max_block_range = max_block_range_for(chain, self._settings.MAX_GET_LOGS_BLOCK_RANGE)
        from_block = bounded_from_block(requested, block, max_block_range)
        if from_block != requested:
            log.warning(
                "block_range_clamped",
                chain=chain,
                from_block=from_block,
                to_block=block,
                max_block_range=max_block_range,
            )
        return from_block

    def _above_threshold(self, event: dict[str, Any]) -> bool:
        event["score"] = self._sentinel.score(event)
        return bool(event["score"] >= self._settings.ALERT_SCORE_THRESHOLD * 100)

    async def _insert_pending(self, events: list[dict[str, Any]]) -> None:
        async with UnitOfWork(self._session_factory) as uow:
            for data in events:
                await uow.candidate_events.create_pending(data)
            await uow.commit()

    @staticmethod
    def _to_pending_data(event: dict[str, Any]) -> dict[str, Any]:
        raw_json = dict(event["raw_json"])
        raw_json["value_usd"] = event.get("value_usd", 0.0)
        return {
            "wallet_id": event["wallet_id"],
            "chain": event["chain"],
            "tx_hash": event["tx_hash"],
            "log_index": event["log_index"],
            "block_number": event["block_number"],
            "event_type": event["event_type"],
            "raw_json": raw_json,
            "score": event.get("score", 0.0),
            "dedupe_key": event["dedupe_key"],
        }
