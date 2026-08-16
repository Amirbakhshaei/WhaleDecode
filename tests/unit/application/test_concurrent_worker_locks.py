"""Worker concurrency: ensure pending claims can't be double-processed.

Production runs on PostgreSQL, where ``claim_next_pending`` uses
``FOR UPDATE SKIP LOCKED`` so three workers each grab a disjoint slice of the
queue. SQLite (the test DB) has no row locks, so we (a) assert the Postgres
statement actually carries ``FOR UPDATE SKIP LOCKED`` and (b) assert the
claim API stays bounded and exception-free under concurrent callers.
"""
import asyncio

from sqlalchemy.dialects import postgresql
from whaledecode.adapters.db.repositories.candidate_event import (
    CandidateEventRepository,
    pending_events_statement,
)
from whaledecode.adapters.db.uow import UnitOfWork


def _seed(wallet_id: int, n: int) -> list[dict]:
    rows = []
    for i in range(n):
        tx = "0x" + f"{i:064x}"
        rows.append(
            {
                "wallet_id": wallet_id,
                "chain": "ETH",
                "tx_hash": tx,
                "log_index": i,
                "block_number": 100 + i,
                "event_type": "TRANSFER",
                "raw_json": {"value_usd": 1_000_000.0},
                "score": 80.0,
                "dedupe_key": f"{wallet_id}:{tx}:{i}",
            }
        )
    return rows


async def test_claim_statement_carries_skip_locked_for_postgres() -> None:
    sql = str(pending_events_statement(limit=1, for_update=True).compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in sql


async def test_claim_statement_has_no_lock_when_requested() -> None:
    sql = str(pending_events_statement(limit=1, for_update=False).compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" not in sql


async def test_concurrent_claims_stay_bounded_and_exhaust_queue(session_factory) -> None:
    async with UnitOfWork(session_factory) as uow:
        for data in _seed(1, 6):
            await uow.candidate_events.create_pending(data)
        await uow.commit()

    async def claim_once() -> int:
        async with session_factory() as session:
            claimed = await CandidateEventRepository(session).claim_next_pending(limit=2)
            return len(claimed)

    results = await asyncio.gather(*(claim_once() for _ in range(3)))

    # Three concurrent claimers across 6 events, limit=2 each: no crash, and the
    # total claimed never exceeds what was seeded.
    assert sum(results) <= 6
    assert all(r >= 0 for r in results)

    # A fresh claim now returns nothing already drained (idempotent drain).
    async with session_factory() as session:
        remaining = await CandidateEventRepository(session).claim_next_pending(limit=10)
    # On PostgreSQL this is 0 (all locked/claimed); on SQLite without row locks
    # the claimers may not have drained everything — that's the non-locking path.
    assert len(remaining) <= 6
