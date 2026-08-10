import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from whaledecode.adapters.db.models.candidate_event import CandidateEventModel
from whaledecode.domain.entities.candidate_event import CandidateEvent
from whaledecode.domain.value_objects.hash import Hash


def pending_events_statement(limit: int = 1, *, for_update: bool = True):
    """Select the oldest pending candidate events, optionally row-locking for claim.

    `FOR UPDATE SKIP LOCKED` makes concurrent workers claim disjoint rows instead
    of racing on the same one.
    """
    stmt = (
        select(CandidateEventModel)
        .where(CandidateEventModel.status == "pending")
        .order_by(CandidateEventModel.created_at.asc(), CandidateEventModel.id.asc())
        .limit(limit)
    )
    if for_update:
        stmt = stmt.with_for_update(skip_locked=True)
    return stmt


class CandidateEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_pending(self, data: dict) -> None:
        """Insert a candidate event with status='pending'; no-op on duplicate dedupe_key."""
        values = {
            "wallet_id": data["wallet_id"],
            "chain": data["chain"],
            "tx_hash": data["tx_hash"],
            "log_index": data["log_index"],
            "block_number": data["block_number"],
            "event_type": data["event_type"],
            "raw_json": json.dumps(data.get("raw_json", {})),
            "score": data.get("score", 0.0),
            "dedupe_key": data["dedupe_key"],
            "status": "pending",
        }
        await self._session.execute(
            self._conflict_ignore_insert()
            .values(**values)
            .on_conflict_do_nothing(index_elements=["dedupe_key"])
        )

    async def claim_next_pending(self, limit: int = 1) -> list[CandidateEvent]:
        """Atomically claim the oldest pending rows (FOR UPDATE SKIP LOCKED on PostgreSQL)."""
        stmt = pending_events_statement(limit, for_update=self._supports_row_lock())
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars()]

    async def set_status(self, event_id: int, status: str, *, attempt_count: int | None = None) -> None:
        values = {"status": status, "updated_at": func.now()}
        if attempt_count is not None:
            values["attempt_count"] = attempt_count
        await self._session.execute(
            update(CandidateEventModel).where(CandidateEventModel.id == event_id).values(**values)
        )

    async def record_failure(self, event_id: int, *, max_attempts: int = 3) -> str:
        """Atomically increment ``attempt_count`` and route the row to ``pending``
        (retry) or ``dead_letter`` (given up). Returns the new status."""
        next_attempt = CandidateEventModel.attempt_count + 1
        new_status = case(
            (next_attempt >= max_attempts, "dead_letter"),
            else_="pending",
        )
        await self._session.execute(
            update(CandidateEventModel)
            .where(CandidateEventModel.id == event_id)
            .values(
                status=new_status,
                attempt_count=next_attempt,
                updated_at=func.now(),
            )
        )
        row = await self._session.execute(
            select(CandidateEventModel.status).where(CandidateEventModel.id == event_id)
        )
        return row.scalar_one()

    async def reap_zombie_events(self, *, minutes: int = 10) -> int:
        """Reset stale ``processing`` rows back to ``pending`` so a crashed worker's
        claims are reclaimed. Returns the number of rows reset."""
        cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
        result = await self._session.execute(
            update(CandidateEventModel)
            .where(CandidateEventModel.status == "processing")
            .where(CandidateEventModel.updated_at < cutoff)
            .values(status="pending", updated_at=func.now())
        )
        return result.rowcount or 0

    async def requeue_stuck_events(self) -> int:
        """Re-queue ``dead_letter``/``skipped`` rows stranded before the MissingGreenlet
        and score-0 ingest fixes. Scores are recomputed from raw_json so a 0.0 bug score
        can't stall an event at the gate again. Returns the number of rows re-queued."""
        result = await self._session.execute(
            select(CandidateEventModel).where(
                CandidateEventModel.status.in_(("dead_letter", "skipped"))
            )
        )
        rows = list(result.scalars())
        if not rows:
            return 0
        await self._requeue_models(rows)
        return len(rows)

    async def requeue_recent_events(self, *, hours: int = 24) -> int:
        """Reset candidate_events created in the last ``hours`` to ``pending`` with
        recomputed scores, so they re-run through the current EventGate and channel
        formatter after a pipeline/format change. Returns the number of rows re-queued."""
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        result = await self._session.execute(
            select(CandidateEventModel).where(CandidateEventModel.created_at >= cutoff)
        )
        rows = list(result.scalars())
        if not rows:
            return 0
        await self._requeue_models(rows)
        return len(rows)

    async def _requeue_models(self, rows: list[CandidateEventModel]) -> None:
        """Recompute each row's score from raw_json and reset claim/attempt state,
        so the EventGate re-evaluates it with current heuristics."""
        from whaledecode.domain.policies.sentinel import SentinelEngine

        engine = SentinelEngine()
        for model in rows:
            raw = json.loads(model.raw_json) if isinstance(model.raw_json, str) else {}
            model.score = engine.score(
                {
                    "event_type": model.event_type,
                    "value_usd": raw.get("value_usd", 0.0),
                    "wallet_id": model.wallet_id,
                    "tx_hash": model.tx_hash,
                },
                curated_wallet_ids={model.wallet_id},
            )
            model.status = "pending"
            model.attempt_count = 0
        await self._session.flush()

    def _supports_row_lock(self) -> bool:
        bind = getattr(self._session.sync_session, "bind", None)
        return bind is not None and bind.dialect.name == "postgresql"

    def _conflict_ignore_insert(self):
        # SQLite and PostgreSQL both support ON CONFLICT DO NOTHING, but only via
        # their dialect-specific Insert construct in SQLAlchemy 2.0.
        if self._supports_row_lock():
            return postgres_insert(CandidateEventModel)
        return sqlite_insert(CandidateEventModel)

    async def create_raw(self, data: dict) -> None:
        model = CandidateEventModel(
            wallet_id=data["wallet_id"],
            chain=data["chain"],
            tx_hash=data["tx_hash"],
            log_index=data["log_index"],
            block_number=data["block_number"],
            event_type=data["event_type"],
            raw_json=data["raw_json"],
            score=data.get("score", 0.0),
            dedupe_key=data["dedupe_key"],
            status="NEW",
        )
        self._session.add(model)
        await self._session.flush()

    async def create(self, event: CandidateEvent) -> CandidateEvent:
        model = CandidateEventModel(
            wallet_id=event.wallet_id,
            chain=event.chain,
            tx_hash=str(event.tx_hash),
            log_index=event.log_index,
            block_number=event.block_number,
            event_type=event.event_type,
            raw_json=json.dumps(event.raw_json),
            score=event.score,
            dedupe_key=event.dedupe_key,
            status=event.status,
            published_at=event.published_at,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

    async def get(self, event_id: int) -> CandidateEvent | None:
        result = await self._session.execute(
            select(CandidateEventModel).where(CandidateEventModel.id == event_id)
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_dedupe_key(self, dedupe_key: str) -> CandidateEvent | None:
        result = await self._session.execute(
            select(CandidateEventModel).where(CandidateEventModel.dedupe_key == dedupe_key)
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def list_by_status(self, status: str, limit: int = 100) -> list[CandidateEvent]:
        result = await self._session.execute(
            select(CandidateEventModel)
            .where(CandidateEventModel.status == status)
            .limit(limit)
        )
        return [self._to_domain(row) for row in result.scalars()]

    async def recent_for_wallet(self, wallet_id: int, since: datetime, limit: int = 50) -> list[CandidateEvent]:
        """Recent events for one wallet within the accumulation window, newest first."""
        result = await self._session.execute(
            select(CandidateEventModel)
            .where(CandidateEventModel.wallet_id == wallet_id)
            .where(CandidateEventModel.created_at >= since)
            .order_by(CandidateEventModel.created_at.desc())
            .limit(limit)
        )
        return [self._to_domain(row) for row in result.scalars()]

    async def mark_published(self, event_id: int) -> None:
        from datetime import UTC, datetime
        result = await self._session.execute(
            select(CandidateEventModel).where(CandidateEventModel.id == event_id)
        )
        model = result.scalar_one_or_none()
        if model:
            model.published_at = datetime.now(UTC)

    async def update(self, event: CandidateEvent) -> CandidateEvent:
        """Upsert by dedupe key so skipped/updated events can be persisted."""
        result = await self._session.execute(
            select(CandidateEventModel).where(CandidateEventModel.dedupe_key == event.dedupe_key)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return await self.create(event)
        model.status = event.status
        model.score = event.score
        model.raw_json = json.dumps(event.raw_json)
        await self._session.flush()
        # server-side onupdate=func.now() expires updated_at on flush; reload it
        # so the sync attribute reads in _to_domain don't trigger a greenlet
        await self._session.refresh(model)
        return self._to_domain(model)

    def _to_domain(self, model: CandidateEventModel) -> CandidateEvent:
        return CandidateEvent(
            id=model.id,
            wallet_id=model.wallet_id,
            chain=model.chain,
            tx_hash=Hash(model.tx_hash),
            log_index=model.log_index,
            block_number=model.block_number,
            event_type=model.event_type,
            raw_json=json.loads(model.raw_json) if isinstance(model.raw_json, str) else {},
            score=model.score,
            dedupe_key=model.dedupe_key,
            status=model.status,
            attempt_count=model.attempt_count,
            published_at=model.published_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
