"""Emergency queue drain: skip pending candidate events under the $50k whale floor.

One-shot ops script to clear a dust backlog that is stalling the worker (FIFO
claims of $0.01 items). Idempotent — re-running skips nothing new.

Usage:
    .venv/bin/python scripts/drain_queue.py
"""
from __future__ import annotations

import asyncio

from sqlalchemy import text
from whaledecode.adapters.db.session import create_session_factory
from whaledecode.config.settings import Settings
from whaledecode.domain.services.event_gate import MIN_WHALE_THRESHOLD_USD


async def drain() -> None:
    settings = Settings()
    async with create_session_factory(settings)() as session:
        print("Draining pending low-value candidate events...")
        result = await session.execute(
            text(
                """
                UPDATE candidate_events
                SET status = 'skipped', score = 0.0, updated_at = NOW()
                WHERE status IN ('pending', 'NEW')
                  AND (
                    raw_json::jsonb->>'value_usd' IS NULL
                    OR (raw_json::jsonb->>'value_usd')::float < :floor
                  );
                """
            ),
            {"floor": MIN_WHALE_THRESHOLD_USD},
        )
        await session.commit()
        print(f"Done! Skipped {result.rowcount} low-value backlog events.")


if __name__ == "__main__":
    asyncio.run(drain())
