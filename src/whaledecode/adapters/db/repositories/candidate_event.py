import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whaledecode.adapters.db.models.candidate_event import CandidateEventModel
from whaledecode.domain.entities.candidate_event import CandidateEvent
from whaledecode.domain.value_objects.hash import Hash


class CandidateEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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

    async def list_unpublished(self, limit: int = 20) -> list[CandidateEvent]:
        result = await self._session.execute(
            select(CandidateEventModel)
            .where(CandidateEventModel.published_at.is_(None))
            .where(CandidateEventModel.score >= 0.7)
            .order_by(CandidateEventModel.score.desc())
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
            published_at=model.published_at,
            created_at=model.created_at,
        )
