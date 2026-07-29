from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whaledecode.adapters.db.models.curated_wallet import CuratedWalletModel
from whaledecode.domain.entities.curated_wallet import CuratedWallet
from whaledecode.domain.value_objects.chain import Chain

_CHAIN_FROM_STR: dict[str, Chain] = {
    "ETH": Chain.ETH,
    "BASE": Chain.BASE,
    "ARB": Chain.ARB,
}


class CuratedWalletRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active(self, chain: str | None = None) -> list[CuratedWallet]:
        stmt = select(CuratedWalletModel).where(CuratedWalletModel.is_active.is_(True))
        if chain is not None:
            stmt = stmt.where(CuratedWalletModel.chain == chain)
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars()]

    async def search_by_label(self, query: str) -> list[CuratedWallet]:
        result = await self._session.execute(
            select(CuratedWalletModel).where(CuratedWalletModel.label.ilike(f"%{query}%"))
        )
        return [self._to_domain(row) for row in result.scalars()]

    async def create(self, wallet: CuratedWallet) -> CuratedWallet:
        model = CuratedWalletModel(
            address=wallet.address,
            chain=wallet.chain.name,
            label=wallet.label,
            tags=",".join(wallet.tags),
            quality_score=wallet.quality_score,
            is_active=wallet.is_active,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

    async def get(self, id: int) -> CuratedWallet | None:
        result = await self._session.execute(select(CuratedWalletModel).where(CuratedWalletModel.id == id))
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_address_and_chain(self, address: str, chain: str) -> CuratedWallet | None:
        result = await self._session.execute(
            select(CuratedWalletModel).where(
                CuratedWalletModel.address == address,
                CuratedWalletModel.chain == chain,
            )
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    def _to_domain(self, model: CuratedWalletModel) -> CuratedWallet:
        return CuratedWallet(
            id=model.id,
            address=model.address,
            chain=_CHAIN_FROM_STR.get(model.chain, Chain.ETH),
            label=model.label,
            tags=[t for t in model.tags.split(",") if t],
            quality_score=model.quality_score,
            is_active=model.is_active,
        )
