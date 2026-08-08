import asyncio
import signal
import sys
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker

from whaledecode.adapters.chain.factory import create_chain_provider
from whaledecode.adapters.chain.normalizer import (
    normalize_log,
    pad_address_to_topic,
    wallet_id_from_transfer_topics,
)
from whaledecode.application.fetcher import (
    _transfer_topic_queries,
    bounded_from_block,
    max_block_range_for,
)
from whaledecode.application.services.investigation import InvestigationService
from whaledecode.config.settings import Settings
from whaledecode.domain.entities.candidate_event import CandidateEvent
from whaledecode.domain.policies.sentinel import SentinelEngine
from whaledecode.domain.value_objects.hash import Hash

log = structlog.get_logger()


async def poll_wallets(
    session_factory: async_sessionmaker,
    settings: Settings,
    investigation_service: InvestigationService,
) -> None:
    """Single polling pass over active curated wallets."""
    from whaledecode.adapters.db.uow import UnitOfWork

    sentinel = SentinelEngine()
    provider = create_chain_provider(settings)

    async with UnitOfWork(session_factory) as uow:
        wallets = await uow.curated_wallets.list_active()
        if not wallets:
            log.info("poll_no_wallets")
            return

        curated_ids = {w.id for w in wallets if w.id is not None}
        chains = set(w.chain.label() for w in wallets)

        # Batch-fetch all recent events once to eliminate N+1 DB connections
        recent_cache: dict[int, list[dict[str, Any]]] = {}
        for wallet_id in curated_ids:
            recent_cache[wallet_id] = await _fetch_recent_events(
                uow, settings.ACCUMULATION_WINDOW_SECONDS, wallet_id
            )

    for chain in chains:
        try:
            block = await provider.get_block_number(chain)
        except Exception as e:
            log.error("poll_block_failed", chain=chain, error=str(e))
            continue

        curated_on_chain = [w for w in wallets if w.chain.label() == chain]
        addresses = [w.address for w in curated_on_chain]
        padded_to_wallet = {
            pad_address_to_topic(w.address): w.id
            for w in curated_on_chain
            if w.id is not None
        }

        for i in range(0, len(addresses), settings.POLL_BATCH_SIZE):
            batch = addresses[i : i + settings.POLL_BATCH_SIZE]
            requested_from = block - settings.REORG_SAFE_BLOCKS
            max_block_range = max_block_range_for(
                chain, settings.MAX_GET_LOGS_BLOCK_RANGE
            )
            from_block = bounded_from_block(requested_from, block, max_block_range)

            if from_block != requested_from:
                log.warning(
                    "block_range_clamped",
                    chain=chain,
                    from_block=from_block,
                    to_block=block,
                    max_block_range=max_block_range,
                )

            padded = [pad_address_to_topic(addr) for addr in batch]
            seen_dedupe_keys: set[str] = set()

            for topics in _transfer_topic_queries(padded):
                try:
                    logs = await provider.get_logs(
                        chain=chain,
                        addresses=[],
                        from_block=from_block,
                        to_block=block,
                        topics=topics,
                    )
                except Exception as e:
                    log.error("poll_logs_failed", chain=chain, batch=i, error=str(e))
                    continue

                investigation_tasks = []

                for raw_log in logs:
                    wallet_id = wallet_id_from_transfer_topics(
                        raw_log.get("topics", []), padded_to_wallet
                    )
                    if wallet_id is None:
                        continue

                    event = normalize_log(raw_log, wallet_id, chain)
                    dedupe_key = event["dedupe_key"]

                    # Guard against processing duplicate topics in the same poll batch
                    if dedupe_key in seen_dedupe_keys:
                        continue
                    seen_dedupe_keys.add(dedupe_key)

                    recent = recent_cache.get(wallet_id, [])
                    score = sentinel.score(
                        event,
                        recent_events=recent,
                        curated_wallet_ids=curated_ids,
                    )
                    event["score"] = score

                    # Maintain state consistency for intra-batch accumulation
                    recent_cache.setdefault(wallet_id, []).append(
                        {"wallet_id": wallet_id, "tx_hash": str(event["tx_hash"])}
                    )

                    if score >= settings.ALERT_SCORE_THRESHOLD * 100:
                        candidate = _to_candidate_event(event)
                        # Schedule concurrent investigation task
                        task = asyncio.create_task(
                            _safe_process_event(investigation_service, candidate)
                        )
                        investigation_tasks.append(task)

                if investigation_tasks:
                    await asyncio.gather(*investigation_tasks)

    log.info("poll_complete", wallet_count=len(wallets))


async def _fetch_recent_events(
    uow: Any, window_seconds: int, wallet_id: int
) -> list[dict[str, Any]]:
    from datetime import UTC, datetime, timedelta

    since = datetime.now(UTC) - timedelta(seconds=window_seconds)
    events = await uow.candidate_events.recent_for_wallet(wallet_id, since)
    return [{"wallet_id": e.wallet_id, "tx_hash": str(e.tx_hash)} for e in events]


async def _safe_process_event(
    investigation_service: InvestigationService, candidate: CandidateEvent
) -> None:
    try:
        await investigation_service.process_event(candidate)
        log.info(
            "candidate_investigated",
            dedupe_key=candidate.dedupe_key,
            score=candidate.score,
        )
    except Exception as e:
        log.warning(
            "candidate_failed", dedupe_key=candidate.dedupe_key, error=str(e)
        )


def _to_candidate_event(event: dict[str, Any]) -> CandidateEvent:
    raw_json = dict(event["raw_json"])
    raw_json["value_usd"] = event.get("value_usd", 0.0)
    return CandidateEvent(
        wallet_id=event["wallet_id"],
        chain=event["chain"],
        tx_hash=Hash(event["tx_hash"]),
        log_index=event["log_index"],
        block_number=event["block_number"],
        event_type=event["event_type"],
        raw_json=raw_json,
        score=event.get("score", 0.0),
        dedupe_key=event["dedupe_key"],
    )


async def run_poll_loop(
    session_factory: async_sessionmaker,
    settings: Settings,
    investigation_service: InvestigationService,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Persistent ingestion loop. Never crashes silently: on any error it logs
    and backs off with a short sleep, so a transient RPC/network blip does not
    kill the process or drop the batch."""
    while not (stop_event and stop_event.is_set()):
        try:
            await poll_wallets(session_factory, settings, investigation_service)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("poll_worker_iteration_failed", error=str(e), exc_info=True)
        try:
            await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            raise


def build_investigation_service(
    settings: Settings,
) -> tuple[async_sessionmaker, InvestigationService]:
    """Wire DB session + LLM graph into an InvestigationService."""
    from whaledecode.adapters.db.session import create_session_factory
    from whaledecode.adapters.db.uow import UnitOfWork
    from whaledecode.adapters.llm.factory import LLMFactory
    from whaledecode.adapters.llm_graph.reasoner import LangGraphReasoner

    session_factory = create_session_factory(settings)
    llm_factory = LLMFactory(settings)
    reasoner = LangGraphReasoner(settings, llm_factory)

    def _uow() -> UnitOfWork:
        return UnitOfWork(session_factory)

    return session_factory, InvestigationService(_uow, reasoner, settings)


async def run_worker() -> None:
    """Entrypoint bootstrap: load settings, wire deps, run the poll loop until signal."""
    from whaledecode.config.logging import setup_logging

    settings = Settings()
    setup_logging(settings)
    settings.inject_langsmith_env()

    session_factory, investigation_service = build_investigation_service(settings)

    log.info("ingestion_worker_started", interval=settings.POLL_INTERVAL_SECONDS)

    stop_event = asyncio.Event()

    def shutdown(sig: int) -> None:
        log.info("ingestion_worker_shutdown_signal", signal=sig)
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: shutdown(s))
        except NotImplementedError:
            pass

    try:
        await run_poll_loop(session_factory, settings, investigation_service, stop_event)
    finally:
        log.info("ingestion_worker_stopped")


if __name__ == "__main__":
    sys.exit(asyncio.run(run_worker()))
