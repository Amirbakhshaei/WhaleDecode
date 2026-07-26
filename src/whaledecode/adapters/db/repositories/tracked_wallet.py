from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whaledecode.adapters.db.models.tracked_wallet import TrackedWalletModel
from whaledecode.domain.entities.tracked_wallet import TrackedWallet
from whaledecode.domain.value_objects.chain import Chain


class TrackedWalletRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_user(self, user_id: int) -> list[TrackedWallet]:
        result = await self._session.execute(
            select(TrackedWalletModel).where(
                TrackedWalletModel.user_id == user_id,
                TrackedWalletModel.is_active.is_(True),
            )
        )
        return [self._to_domain(row) for row in result.scalars()]

    async def create(self, wallet: TrackedWallet) -> TrackedWallet:
        model = TrackedWalletModel(
            user_id=wallet.user_id,
            wallet_id=wallet.wallet_id,
            chain=wallet.chain.value,
            alias=wallet.alias,
            is_active=wallet.is_active,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

    async def deactivate(self, id: int) -> None:
        result = await self._session.execute(select(TrackedWalletModel).where(TrackedWalletModel.id == id))
        model = result.scalar_one_or_none()
        if model is not None:
            model.is_active = False

    async def count_active_by_user(self, user_id: int) -> int:
        result = await self._session.execute(
            select(TrackedWalletModel).where(
                TrackedWalletModel.user_id == user_id,
                TrackedWalletModel.is_active.is_(True),
            )
        )
        return len(result.scalars().all())

    def _to_domain(self, model: TrackedWalletModel) -> TrackedWallet:
        return TrackedWallet(
            id=model.id,
            user_id=model.user_id,
            wallet_id=model.wallet_id,
            chain=Chain(model.chain),
            alias=model.alias,
            is_active=model.is_active,
            created_at=model.created_at,
        )
