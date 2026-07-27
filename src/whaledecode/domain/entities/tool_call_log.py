from datetime import UTC, datetime

from pydantic import BaseModel, Field


class ToolCallLog(BaseModel):
    id: int | None = None
    agent_run_id: int
    tool_name: str
    input_json: dict = Field(default_factory=dict)
    output_json: dict | None = None
    latency_ms: int = 0
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
