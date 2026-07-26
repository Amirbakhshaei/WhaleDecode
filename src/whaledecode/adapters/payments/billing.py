from datetime import UTC, datetime, timedelta

from whaledecode.config.settings import Settings
from whaledecode.config.tiers import PlanCode, PlanLimits
from whaledecode.domain.ports.billing import BillingPort, LimitCheck


class StubBillingPort(BillingPort):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def get_plan(self, user_id: int) -> str:
        return PlanCode.FREE

    async def grant_plan(self, user_id: int, plan_code: str, expires_at: datetime | None = None) -> None:
        if expires_at is None:
            expires_at = datetime.now(UTC) + timedelta(days=30)

    async def check_limit(self, user_id: int, limit_type: str) -> LimitCheck:
        limits = PlanLimits.for_plan(PlanCode.FREE)
        cap = limits.get(limit_type, 0)
        return LimitCheck(
            allowed=cap > 0,
            current=0,
            limit=cap,
            reset_at=datetime.now(UTC) + timedelta(hours=24),
        )

    async def increment_usage(self, user_id: int, limit_type: str) -> None:
        pass
