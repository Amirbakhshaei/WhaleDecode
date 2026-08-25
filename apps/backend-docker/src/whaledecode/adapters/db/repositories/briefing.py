import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from whaledecode.adapters.db.models.briefing import BriefingModel
from whaledecode.domain.entities.briefing import Briefing


class BriefingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, briefing: Briefing) -> Briefing:
        model = BriefingModel(
            user_id=briefing.user_id,
            date=briefing.date,
            summary_md=briefing.summary_md,
            events_json=json.dumps(briefing.events_json),
            sent_at=briefing.sent_at,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

    async def get_by_user_and_date(self, user_id: int, date: str) -> Briefing | None:
        import datetime
        dt = datetime.date.fromisoformat(date)
        result = await self._session.execute(
            select(BriefingModel).where(
                BriefingModel.user_id == user_id,
                BriefingModel.date == dt,
            )
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    def _to_domain(self, model: BriefingModel) -> Briefing:
        return Briefing(
            id=model.id,
            user_id=model.user_id,
            date=model.date,
            summary_md=model.summary_md,
            events_json=json.loads(model.events_json) if isinstance(model.events_json, str) else [],
            sent_at=model.sent_at,
        )
