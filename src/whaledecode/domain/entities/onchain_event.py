from datetime import datetime

from pydantic import BaseModel, Field


class OnchainEvent(BaseModel):
    id: int | None = None
    candidate_id: int
    wallet_id: int
    chain: str
    tx_hash: str
    block_number: int
    timestamp: datetime
    event_type: str
    decoded: dict = Field(default_factory=dict)
    enriched_json: dict = Field(default_factory=dict)
