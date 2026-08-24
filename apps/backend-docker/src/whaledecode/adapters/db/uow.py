from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from whaledecode.adapters.db.repositories.admin_audit_log import AdminAuditLogRepository
from whaledecode.adapters.db.repositories.agent_run import AgentRunRepository
from whaledecode.adapters.db.repositories.alert import AlertRepository
from whaledecode.adapters.db.repositories.briefing import BriefingRepository
from whaledecode.adapters.db.repositories.campaign import CampaignRepository
from whaledecode.adapters.db.repositories.candidate_event import CandidateEventRepository
from whaledecode.adapters.db.repositories.curated_wallet import CuratedWalletRepository
from whaledecode.adapters.db.repositories.edge_intelligence import (
    FundingEdgeRepository,
    WalletProfileRepository,
)
from whaledecode.adapters.db.repositories.tracked_wallet import TrackedWalletRepository
from whaledecode.adapters.db.repositories.user import UserRepository


class UnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> "UnitOfWork":
        self._session = self._session_factory()
        self.users = UserRepository(self._session)
        self.curated_wallets = CuratedWalletRepository(self._session)
        self.tracked_wallets = TrackedWalletRepository(self._session)
        self.candidate_events = CandidateEventRepository(self._session)
        self.campaigns = CampaignRepository(self._session)
        self.alerts = AlertRepository(self._session)
        self.agent_runs = AgentRunRepository(self._session)
        self.briefings = BriefingRepository(self._session)
        self.admin_audit_logs = AdminAuditLogRepository(self._session)
        self.wallet_profiles = WalletProfileRepository(self._session)
        self.funding_edges = FundingEdgeRepository(self._session)
        return self

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("UnitOfWork session not entered")
        return self._session

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._session is not None:
            if exc_type is not None:
                await self._session.rollback()
            await self._session.close()

    async def commit(self) -> None:
        if self._session is not None:
            await self._session.commit()

    async def rollback(self) -> None:
        if self._session is not None:
            await self._session.rollback()
