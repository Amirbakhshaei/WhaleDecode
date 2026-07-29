from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whaledecode.adapters.db.models.alert import AlertModel
from whaledecode.domain.entities.alert import Alert


class AlertRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, alert: Alert) -> Alert:
        model = AlertModel(
            user_id=alert.user_id,
            event_id=alert.event_id,
            status=alert.status,
            priority=alert.priority,
            dedupe_key=alert.dedupe_key,
            sent_at=alert.sent_at,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

    async def get_by_dedupe_key(self, dedupe_key: str) -> Alert | None:
        result = await self._session.execute(
            select(AlertModel).where(AlertModel.dedupe_key == dedupe_key)
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def list_by_user(self, user_id: int, limit: int = 50) -> list[Alert]:
        result = await self._session.execute(
            select(AlertModel).where(AlertModel.user_id == user_id).limit(limit)
        )
        return [self._to_domain(row) for row in result.scalars()]

    async def update(self, alert: Alert) -> None:
        result = await self._session.execute(select(AlertModel).where(AlertModel.id == alert.id))
        model = result.scalar_one_or_none()
        if model is None:
            return
        model.status = alert.status
        model.sent_at = alert.sent_at

    async def list_by_status(self, status: str, limit: int = 100) -> list[Alert]:
        result = await self._session.execute(
            select(AlertModel).where(AlertModel.status == status).limit(limit)
        )
        return [self._to_domain(row) for row in result.scalars()]

    def _to_domain(self, model: AlertModel) -> Alert:
        return Alert(
            id=model.id,
            user_id=model.user_id,
            event_id=model.event_id,
            status=model.status,
            priority=model.priority,
            dedupe_key=model.dedupe_key,
            sent_at=model.sent_at,
        )
