from datetime import UTC, datetime

from pydantic import BaseModel, Field
from whaledecode.config.tiers import get_limits


class User(BaseModel):
    id: int | None = None
    tg_id: int
    username: str | None = None
    plan: str = "free"
    tier: str = "free"
    plan_expires_at: datetime | None = None
    daily_chat_count: int = 0
    daily_alert_count: int = 0
    # Daily free-tier intelligence budget, decremented by the quota gate.
    queries_remaining: int = Field(default_factory=lambda: get_limits("free").chat_per_day)
    is_admin: bool = False
    alerts_enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
