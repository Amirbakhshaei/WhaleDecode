import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker

from whaledecode.adapters.chain.factory import create_chain_provider
from whaledecode.adapters.chain.normalizer import normalize_log
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


async def poll_wallets(session_factory: async_sessionmaker, settings: Settings) -> None:
    from whaledecode.adapters.db.uow import UnitOfWork

    sentinel = SentinelEngine()
    provider = create_chain_provider(settings)

    uow = UnitOfWork(session_factory)
    async with uow:
        wallets = await uow.curated_wallets.list_active()
        if not wallets:
            log.info("poll_no_wallets")
            return

        chains = set(w.chain.label() for w in wallets)

        for chain in chains:
            try:
                block = await provider.get_block_number(chain)
            except Exception as e:
                log.error("poll_block_failed", chain=chain, error=str(e))
                continue

            curated_on_chain = [w for w in wallets if w.chain.label() == chain]
            addresses = [w.address for w in curated_on_chain]

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
                try:
                    logs = await provider.get_logs(
                        chain=chain,
                        addresses=batch,
                        from_block=from_block,
                        to_block=block,
                        topics=[],
                    )
                except Exception as e:
                    log.error("poll_logs_failed", chain=chain, batch=i, error=str(e))
                    continue

                addr_map = {w.address: w.id for w in curated_on_chain}
                for raw_log in logs:
                    log_addr = raw_log.get("address", "")
                    wallet_id = addr_map.get(log_addr)
                    if wallet_id is None:
                        continue
                    event = normalize_log(raw_log, wallet_id, chain)
                    event["score"] = sentinel.score(event)
                    if event["score"] >= settings.ALERT_SCORE_THRESHOLD * 100:
                        try:
                            existing = await uow.candidate_events.get_by_dedupe_key(event["dedupe_key"])
                            if existing:
                                continue
                            await uow.candidate_events.create_raw(event)
                            log.info("candidate_created", dedupe_key=event["dedupe_key"], score=event["score"])
                        except Exception as e:
                            log.warning("candidate_duplicate", dedupe_key=event["dedupe_key"], error=str(e))
                await uow.commit()

    log.info("poll_complete", wallet_count=len(wallets))
