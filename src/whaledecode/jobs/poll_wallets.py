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

    for chain in chains:
        try:
            block = await provider.get_block_number(chain)
        except Exception as e:
            log.error("poll_block_failed", chain=chain, error=str(e))
            continue

        curated_on_chain = [w for w in wallets if w.chain.label() == chain]
        addresses = [w.address for w in curated_on_chain]
        padded_to_wallet = {
            pad_address_to_topic(w.address): w.id for w in curated_on_chain if w.id is not None
        }

        for i in range(0, len(addresses), settings.POLL_BATCH_SIZE):
                batch = addresses[i : i + settings.POLL_BATCH_SIZE]
                requested_from = block - settings.REORG_SAFE_BLOCKS
                max_block_range = max_block_range_for(chain, settings.MAX_GET_LOGS_BLOCK_RANGE)
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
                recent_cache: dict[int, list[dict[str, Any]]] = {}
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

                    for raw_log in logs:
                        wallet_id = wallet_id_from_transfer_topics(raw_log.get("topics", []), padded_to_wallet)
                        if wallet_id is None:
                            continue
                        event = normalize_log(raw_log, wallet_id, chain)
                        recent = recent_cache.get(wallet_id)
                        if recent is None:
                            recent = await recent_for_wallet(session_factory, settings, wallet_id)
                            recent_cache[wallet_id] = recent
                        event["score"] = sentinel.score(event, recent_events=recent, curated_wallet_ids=curated_ids)
                        if event["score"] >= settings.ALERT_SCORE_THRESHOLD * 100:
                            try:
                                await investigation_service.process_event(_to_candidate_event(event))
                                log.info("candidate_investigated", dedupe_key=event["dedupe_key"], score=event["score"])
                            except Exception as e:
                                log.warning("candidate_failed", dedupe_key=event["dedupe_key"], error=str(e))

    log.info("poll_complete", wallet_count=len(wallets))


async def recent_for_wallet(
    session_factory: async_sessionmaker,
    settings: Settings,
    wallet_id: int,
) -> list[dict[str, Any]]:
    from datetime import UTC, datetime, timedelta

    from whaledecode.adapters.db.uow import UnitOfWork

    since = datetime.now(UTC) - timedelta(seconds=settings.ACCUMULATION_WINDOW_SECONDS)
    async with UnitOfWork(session_factory) as uow:
        events = await uow.candidate_events.recent_for_wallet(wallet_id, since)
    return [{"wallet_id": e.wallet_id, "tx_hash": str(e.tx_hash)} for e in events]


def _to_candidate_event(event: dict) -> CandidateEvent:
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
