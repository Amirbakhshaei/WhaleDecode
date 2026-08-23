from cachetools import TTLCache
from sqlalchemy import bindparam, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from whaledecode.adapters.db.models.curated_wallet import CuratedWalletModel
from whaledecode.domain.entities.curated_wallet import CuratedWallet
from whaledecode.domain.value_objects.chain import Chain

_CHAIN_FROM_STR: dict[str, Chain] = {
    "ETH": Chain.ETH,
    "BASE": Chain.BASE,
    "ARB": Chain.ARB,
}

# Cache list_active results per chain for 300 seconds (5 min)
# Key: chain name (or "all" for no filter), Value: list[CuratedWallet]
_ACTIVE_WALLET_CACHE: TTLCache = TTLCache(maxsize=10, ttl=300)


def reset_wallet_cache() -> None:
    """Clear the wallet cache (useful for tests)."""
    _ACTIVE_WALLET_CACHE.clear()


class CuratedWalletRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active(self, chain: str | None = None) -> list[CuratedWallet]:
        cache_key = chain or "all"
        if cache_key in _ACTIVE_WALLET_CACHE:
            return _ACTIVE_WALLET_CACHE[cache_key]

        stmt = select(CuratedWalletModel).where(CuratedWalletModel.is_active.is_(True))
        if chain is not None:
            stmt = stmt.where(CuratedWalletModel.chain == chain)
        result = await self._session.execute(stmt)
        wallets = [self._to_domain(row) for row in result.scalars()]
        _ACTIVE_WALLET_CACHE[cache_key] = wallets
        return wallets

    async def search_by_label(self, query: str) -> list[CuratedWallet]:
        result = await self._session.execute(
            select(CuratedWalletModel).where(CuratedWalletModel.label.ilike(f"%{query}%"))
        )
        return [self._to_domain(row) for row in result.scalars()]

    async def find_by_addresses(self, addresses: list[str]) -> list[CuratedWallet]:
        """Reverse-lookup curated wallets by (lowercased) address."""
        if not addresses:
            return []
        stmt = select(CuratedWalletModel).where(
            or_(
                *(func.lower(CuratedWalletModel.address) == addr.lower() for addr in addresses)
            )
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars()]

    async def search_by_label_or_category(self, query: str, limit: int = 5) -> list[CuratedWallet]:
        stmt = (
            select(CuratedWalletModel)
            .where(
                or_(
                    CuratedWalletModel.label.ilike(f"%{query}%"),
                    CuratedWalletModel.category.ilike(f"%{query}%"),
                )
            )
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars()]

    async def create(self, wallet: CuratedWallet) -> CuratedWallet:
        model = CuratedWalletModel(
            address=wallet.address,
            chain=wallet.chain.name,
            label=wallet.label,
            tags=",".join(wallet.tags),
            quality_score=wallet.quality_score,
            is_active=wallet.is_active,
            is_monitored_active=wallet.is_monitored_active,
            tx_count_30d=wallet.tx_count_30d,
            velocity_penalty=wallet.velocity_penalty,
            category=wallet.category,
        )
        self._session.add(model)
        await self._session.flush()
        _ACTIVE_WALLET_CACHE.clear()
        return self._to_domain(model)

    async def get(self, id: int) -> CuratedWallet | None:
        result = await self._session.execute(select(CuratedWalletModel).where(CuratedWalletModel.id == id))
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def update(self, wallet: CuratedWallet) -> None:
        result = await self._session.execute(
            select(CuratedWalletModel).where(CuratedWalletModel.id == wallet.id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return
        model.is_active = wallet.is_active
        model.label = wallet.label
        model.tags = ",".join(wallet.tags)
        model.quality_score = wallet.quality_score
        model.category = wallet.category
        model.is_monitored_active = wallet.is_monitored_active
        _ACTIVE_WALLET_CACHE.clear()

    async def get_by_address_and_chain(self, address: str, chain: str) -> CuratedWallet | None:
        result = await self._session.execute(
            select(CuratedWalletModel).where(
                func.lower(CuratedWalletModel.address) == func.lower(address),
                func.upper(CuratedWalletModel.chain) == func.upper(chain),
            )
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def set_monitored_flags(self, monitored_addresses: set[str]) -> None:
        """Atomically reconcile ``is_monitored_active`` with the active 300 set.

        Every address not in ``monitored_addresses`` is flipped to FALSE in the
        same transaction, so the column always reflects exactly the wallets
        currently registered on the Alchemy webhook.
        """
        normalized = {a.lower() for a in monitored_addresses}
        await self._session.execute(
            CuratedWalletModel.__table__.update()
            .values(is_monitored_active=False)
        )
        if normalized:
            stmt = text(
                "UPDATE curated_wallets SET is_monitored_active = TRUE "
                "WHERE lower(address) IN :addrs"
            ).bindparams(bindparam("addrs", expanding=True))
            await self._session.execute(stmt, {"addrs": list(normalized)})
        _ACTIVE_WALLET_CACHE.clear()

    def _to_domain(self, model: CuratedWalletModel) -> CuratedWallet:
        return CuratedWallet(
            id=model.id,
            address=model.address,
            chain=_CHAIN_FROM_STR.get(model.chain, Chain.ETH),
            label=model.label,
            tags=[t for t in model.tags.split(",") if t],
            quality_score=model.quality_score,
            category=model.category,
            is_active=model.is_active,
            is_monitored_active=model.is_monitored_active,
            tx_count_30d=model.tx_count_30d,
            last_activity_at=str(model.last_activity_at) if model.last_activity_at else None,
            velocity_penalty=model.velocity_penalty,
        )
