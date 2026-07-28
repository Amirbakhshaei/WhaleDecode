from whaledecode.domain.entities.curated_wallet import CuratedWallet
from whaledecode.domain.entities.tracked_wallet import TrackedWallet
from whaledecode.domain.value_objects.chain import Chain


class WalletService:
    def __init__(self, uow_factory) -> None:
        self._uow_factory = uow_factory

    async def list_curated(self, chain: str | None = None) -> list[CuratedWallet]:
        async with self._uow_factory() as uow:
            return await uow.curated_wallets.list_active(chain=chain)

    async def search_curated(self, query: str) -> list[CuratedWallet]:
        async with self._uow_factory() as uow:
            return await uow.curated_wallets.search_by_label(query)

    async def track(self, user_id: int, wallet_id: int, chain: str) -> TrackedWallet:
        async with self._uow_factory() as uow:
            wallet = TrackedWallet(
                user_id=user_id,
                wallet_id=wallet_id,
                chain=Chain[chain],
            )
            result = await uow.tracked_wallets.create(wallet)
            await uow.commit()
            return result

    async def untrack(self, user_id: int, curated_wallet_id: int) -> None:
        async with self._uow_factory() as uow:
            tracked_list = await uow.tracked_wallets.list_by_user(user_id)
            for tw in tracked_list:
                if tw.wallet_id == curated_wallet_id:
                    await uow.tracked_wallets.deactivate(tw.id)
                    break
            await uow.commit()

    async def list_tracked(self, user_id: int) -> list[TrackedWallet]:
        async with self._uow_factory() as uow:
            return await uow.tracked_wallets.list_by_user(user_id)
