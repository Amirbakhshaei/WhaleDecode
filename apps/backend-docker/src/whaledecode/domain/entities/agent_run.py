from datetime import UTC, datetime

from pydantic import BaseModel, Field


class AgentRun(BaseModel):
    id: int | None = None
    trigger_type: str  # event / chat / briefing
    trigger_ref_id: int | None = None
    graph_name: str
    status: str = "pending"
    input_json: dict = Field(default_factory=dict)
    output_json: dict | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
