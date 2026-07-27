from datetime import UTC, datetime

from pydantic import BaseModel, Field

from whaledecode.domain.value_objects.chain import Chain


class TrackedWallet(BaseModel):
    id: int | None = None
    user_id: int
    wallet_id: int
    chain: Chain
    alias: str | None = None
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
