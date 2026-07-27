from datetime import UTC, datetime

from pydantic import BaseModel, Field

from whaledecode.domain.value_objects.hash import Hash


class CandidateEvent(BaseModel):
    id: int | None = None
    wallet_id: int
    chain: str
    tx_hash: Hash
    log_index: int
    block_number: int
    event_type: str = "UNKNOWN"
    raw_json: dict = Field(default_factory=dict)
    score: float = 0.0
    dedupe_key: str = ""
    status: str = "NEW"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
