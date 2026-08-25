"""Producer: live blockchain fetcher.

Polls RPC nodes, decodes logs, and queues ``pending`` candidate_events for the
consumer worker. This module is deliberately I/O bound to the chain provider and
the database only — it must not import or call the investigation service or any
LangChain/LLM component.
"""
import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from whaledecode.adapters.chain.factory import create_chain_provider
from whaledecode.adapters.chain.normalizer import (
    TRANSFER_EVENT_SIGNATURE,
    normalize_log,
    pad_address_to_topic,
    wallet_id_from_transfer_topics,
)
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


def _transfer_topic_queries(padded_wallets: list[str]) -> list[list[Any]]:
    """Two eth_getLogs topic filters, one per transfer direction.

    ``[SIG, [wallets], null]`` = outgoing (any of our wallets is the ``from``).
    ``[SIG, null, [wallets]]`` = incoming (any of our wallets is the ``to``).
    """
    return [
        [TRANSFER_EVENT_SIGNATURE, padded_wallets, None],
        [TRANSFER_EVENT_SIGNATURE, None, padded_wallets],
    ]


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
                log.error("fetcher_loop_error", extra={"error": str(e)}, exc_info=True)
            try:
                await asyncio.sleep(self._settings.POLL_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                raise

    async def poll_once(self) -> None:
        """One fetch pass: wallets → head block → logs → pending inserts."""
        async with UnitOfWork(self._session_factory) as uow:
            wallets = await uow.curated_wallets.list_active()

        if not wallets:
            log.info("fetcher_no_wallets", extra={})
            return

        curated_ids = {w.id for w in wallets if w.id is not None}
        chains = {w.chain.label() for w in wallets}
        for chain in chains:
            try:
                block = await self._provider.get_block_number(chain)
            except Exception as e:
                log.error("fetcher_block_failed", extra={"chain": chain, "error": str(e)})
                continue

            on_chain = [w for w in wallets if w.chain.label() == chain]
            padded_to_wallet = {
                pad_address_to_topic(w.address): w.id for w in on_chain if w.id is not None
            }
            addresses = [w.address for w in on_chain]
            from_block = self._from_block(chain, block)

            for i in range(0, len(addresses), self._settings.POLL_BATCH_SIZE):
                batch = addresses[i : i + self._settings.POLL_BATCH_SIZE]
                padded = [pad_address_to_topic(addr) for addr in batch]
                pending: list[dict[str, Any]] = []
                recent_cache: dict[int, list[dict[str, Any]]] = {}
                for topics in _transfer_topic_queries(padded):
                    try:
                        logs = await self._provider.get_logs(
                            chain=chain,
                            addresses=[],
                            from_block=from_block,
                            to_block=block,
                            topics=topics,
                        )
                    except Exception as e:
                        log.error("fetcher_logs_failed", extra={"chain": chain, "batch": i, "error": str(e)})
                        continue
                    for raw_log in logs:
                        wallet_id = wallet_id_from_transfer_topics(raw_log.get("topics", []), padded_to_wallet)
                        if wallet_id is None:
                            continue
                        event = normalize_log(raw_log, wallet_id, chain)
                        recent = recent_cache.get(wallet_id)
                        if recent is None:
                            recent = await self._recent_events(wallet_id)
                            recent_cache[wallet_id] = recent
                        if self._above_threshold(event, recent, curated_ids):
                            pending.append(self._to_pending_data(event))
                if pending:
                    await self._insert_pending(pending)
                    log.info("fetcher_inserted", extra={"chain": chain, "count": len(pending)})

        log.info("fetcher_poll_complete", extra={"wallet_count": len(wallets)})

    def _from_block(self, chain: str, block: int) -> int:
        requested = block - self._settings.REORG_SAFE_BLOCKS
        max_block_range = max_block_range_for(chain, self._settings.MAX_GET_LOGS_BLOCK_RANGE)
        from_block = bounded_from_block(requested, block, max_block_range)
        if from_block != requested:
            log.warning(
                "block_range_clamped",
                extra={
                    "chain": chain,
                    "from_block": from_block,
                    "to_block": block,
                    "max_block_range": max_block_range,
                },
            )
        return from_block

    async def _recent_events(self, wallet_id: int) -> list[dict[str, Any]]:
        """Fetch this wallet's recent events so scoring can reward accumulation/confluence."""
        since = datetime.now(UTC) - timedelta(seconds=self._settings.ACCUMULATION_WINDOW_SECONDS)
        async with UnitOfWork(self._session_factory) as uow:
            events = await uow.candidate_events.recent_for_wallet(wallet_id, since)
        return [{"wallet_id": e.wallet_id, "tx_hash": str(e.tx_hash)} for e in events]

    def _above_threshold(
        self,
        event: dict[str, Any],
        recent_events: list[dict[str, Any]] | None = None,
        curated_wallet_ids: set[int] | None = None,
    ) -> bool:
        event["score"] = self._sentinel.score(
            event, recent_events=recent_events, curated_wallet_ids=curated_wallet_ids
        )
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
