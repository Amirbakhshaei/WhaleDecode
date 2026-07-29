from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whaledecode.adapters.db.models.user import UserModel
from whaledecode.domain.entities.user import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: int) -> User | None:
        result = await self._session.execute(select(UserModel).where(UserModel.id == user_id))
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_tg_id(self, tg_id: int) -> User | None:
        result = await self._session.execute(select(UserModel).where(UserModel.tg_id == tg_id))
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def create(self, user: User) -> User:
        model = UserModel(
            tg_id=user.tg_id,
            username=user.username,
            plan=user.plan,
            plan_expires_at=user.plan_expires_at,
            daily_chat_count=user.daily_chat_count,
            daily_alert_count=user.daily_alert_count,
            is_admin=user.is_admin,
            alerts_enabled=user.alerts_enabled,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

    async def update(self, user: User) -> None:
        result = await self._session.execute(select(UserModel).where(UserModel.id == user.id))
        model = result.scalar_one_or_none()
        if model is None:
            return
        model.username = user.username
        model.plan = user.plan
        model.plan_expires_at = user.plan_expires_at
        model.daily_chat_count = user.daily_chat_count
        model.daily_alert_count = user.daily_alert_count
        model.is_admin = user.is_admin
        model.alerts_enabled = user.alerts_enabled

    async def list_by_plan(self, plan: str) -> list[User]:
        result = await self._session.execute(select(UserModel).where(UserModel.plan == plan))
        return [self._to_domain(row) for row in result.scalars()]

    def _to_domain(self, model: UserModel) -> User:
        return User(
            id=model.id,
            tg_id=model.tg_id,
            username=model.username,
            plan=model.plan,
            plan_expires_at=model.plan_expires_at,
            daily_chat_count=model.daily_chat_count,
            daily_alert_count=model.daily_alert_count,
            is_admin=model.is_admin,
            alerts_enabled=model.alerts_enabled,
            created_at=model.created_at,
        )
