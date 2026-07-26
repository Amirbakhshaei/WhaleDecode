from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.domain.entities.curated_wallet import CuratedWallet
from whaledecode.domain.entities.tracked_wallet import TrackedWallet
from whaledecode.domain.value_objects.chain import Chain


class WalletService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def list_curated(self, chain: str | None = None) -> list[CuratedWallet]:
        return await self._uow.curated_wallets.list_active(chain=chain)

    async def search_curated(self, query: str) -> list[CuratedWallet]:
        return await self._uow.curated_wallets.search_by_label(query)

    async def track(self, user_id: int, wallet_id: int, chain: str) -> TrackedWallet:
        wallet = TrackedWallet(
            user_id=user_id,
            wallet_id=wallet_id,
            chain=Chain(chain.upper()),
        )
        result = await self._uow.tracked_wallets.create(wallet)
        await self._uow.commit()
        return result

    async def untrack(self, wallet_id: int) -> None:
        await self._uow.tracked_wallets.deactivate(wallet_id)
        await self._uow.commit()

    async def list_tracked(self, user_id: int) -> list[TrackedWallet]:
        return await self._uow.tracked_wallets.list_by_user(user_id)
