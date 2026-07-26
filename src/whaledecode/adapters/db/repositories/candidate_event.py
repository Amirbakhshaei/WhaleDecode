import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whaledecode.adapters.db.models.candidate_event import CandidateEventModel
from whaledecode.domain.entities.candidate_event import CandidateEvent
from whaledecode.domain.value_objects.hash import Hash


class CandidateEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

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
            created_at=model.created_at,
        )
