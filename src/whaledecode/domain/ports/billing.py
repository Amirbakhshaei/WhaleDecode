from datetime import datetime
from typing import Protocol


class LimitCheck:
    allowed: bool
    current: int
    limit: int
    reset_at: datetime | None = None


class BillingPort(Protocol):
    async def get_plan(self, user_id: int) -> str: ...

    async def grant_plan(self, user_id: int, plan_code: str, expires_at: datetime | None = None) -> None: ...

    async def check_limit(self, user_id: int, limit_type: str) -> LimitCheck: ...

    async def increment_usage(self, user_id: int, limit_type: str) -> None: ...
