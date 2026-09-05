"""Repositories for wallet_profiles, funding_edges, and syndicate_clusters (Modules 1, 2 & 2.1)."""
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from whaledecode.adapters.db.models.funding_edge import FundingEdgeModel
from whaledecode.adapters.db.models.syndicate_cluster import SyndicateClusterModel
from whaledecode.adapters.db.models.wallet_profile import WalletProfileModel


def _upsert(session: AsyncSession) -> Any:
    """Postgres in prod, SQLite in tests."""
    if session.bind is not None and session.bind.dialect.name == "sqlite":
        return sqlite_insert
    return pg_insert


class WalletProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, values: dict[str, Any]) -> None:
        stmt = _upsert(self._session)(
            WalletProfileModel.__table__
        ).values(**values)
        update_cols = {
            c: getattr(stmt.excluded, c)
            for c in (
                "historical_win_rate_30d",
                "avg_holding_period_days",
                "primary_strategy",
                "total_pnl_usd",
                "recent_actions_summary",
                "sample_size_30d",
                "source",
            )
        }
        await self._session.execute(
            stmt.on_conflict_do_update(index_elements=["chain", "address"], set_=update_cols)
        )

    async def get(self, chain: str, address: str) -> WalletProfileModel | None:
        result = await self._session.execute(
            select(WalletProfileModel).where(
                WalletProfileModel.chain == chain.lower(),
                WalletProfileModel.address == address.lower(),
            )
        )
        return result.scalar_one_or_none()


class FundingEdgeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_edge(self, values: dict[str, Any]) -> None:
        """Idempotent edge write (ON CONFLICT DO NOTHING on child+tx_hash)."""
        stmt = _upsert(self._session)(FundingEdgeModel.__table__).values(**values)
        await self._session.execute(stmt.on_conflict_do_nothing(index_elements=["child_address", "tx_hash"]))

    async def upstream_funders(self, address: str, within_hours: int = 24) -> list[FundingEdgeModel]:
        """Edges funding ``address`` in the trailing window (genesis-fund lookup)."""
        since = datetime.now(UTC) - timedelta(hours=within_hours)
        result = await self._session.execute(
            select(FundingEdgeModel)
            .where(
                FundingEdgeModel.child_address == address.lower(),
                FundingEdgeModel.created_at >= since,
            )
            .order_by(FundingEdgeModel.created_at.desc())
        )
        return list(result.scalars())

    async def siblings_funded_by(self, root_address: str, exclude: str, within_hours: int = 24) -> list[str]:
        """Distinct sibling children funded by the same root in the window."""
        since = datetime.now(UTC) - timedelta(hours=within_hours)
        result = await self._session.execute(
            select(FundingEdgeModel.child_address)
            .where(
                FundingEdgeModel.root_address == root_address.lower(),
                FundingEdgeModel.child_address != exclude.lower(),
                FundingEdgeModel.created_at >= since,
            )
            .distinct()
        )
        return [row[0] for row in result.all()]


class SyndicateClusterRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_cluster(self, values: dict[str, Any]) -> UUID | None:
        """Create or update a syndicate cluster. Returns the cluster ID."""
        stmt = _upsert(self._session)(SyndicateClusterModel.__table__).values(**values)
        update_cols = {
            c: getattr(stmt.excluded, c)
            for c in (
                "wallet_count",
                "total_usd",
                "window_end",
                "updated_at",
            )
        }
        result = await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=["root_address", "token_address", "window_start"],
                set_=update_cols,
            ).returning(SyndicateClusterModel.id)
        )
        return result.scalar_one_or_none()

    async def get_cluster(self, root_address: str, token_address: str, window_start: datetime) -> SyndicateClusterModel | None:
        """Get a specific cluster by root, token, and window."""
        result = await self._session.execute(
            select(SyndicateClusterModel).where(
                SyndicateClusterModel.root_address == root_address.lower(),
                SyndicateClusterModel.token_address == token_address.lower(),
                SyndicateClusterModel.window_start == window_start,
            )
        )
        return result.scalar_one_or_none()

    async def list_recent_clusters(self, chain: str | None = None, hours: int = 24, limit: int = 10) -> list[SyndicateClusterModel]:
        """List recent clusters, optionally filtered by chain."""
        since = datetime.now(UTC) - timedelta(hours=hours)
        query = select(SyndicateClusterModel).where(
            SyndicateClusterModel.window_end >= since
        ).order_by(SyndicateClusterModel.total_usd.desc()).limit(limit)
        if chain:
            query = query.where(SyndicateClusterModel.chain == chain.lower())
        result = await self._session.execute(query)
        return list(result.scalars())

    async def get_clusters_for_token(self, token_address: str, hours: int = 24) -> list[SyndicateClusterModel]:
        """Get all clusters for a specific token in the time window."""
        since = datetime.now(UTC) - timedelta(hours=hours)
        result = await self._session.execute(
            select(SyndicateClusterModel).where(
                SyndicateClusterModel.token_address == token_address.lower(),
                SyndicateClusterModel.window_end >= since,
            ).order_by(SyndicateClusterModel.total_usd.desc())
        )
        return list(result.scalars())
