from datetime import UTC, datetime

from pydantic import BaseModel, Field


class User(BaseModel):
    id: int | None = None
    tg_id: int
    username: str | None = None
    plan: str = "free"
    plan_expires_at: datetime | None = None
    daily_chat_count: int = 0
    daily_alert_count: int = 0
    is_admin: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
