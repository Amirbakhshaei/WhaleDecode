from pydantic import BaseModel, Field


class ReasoningReport(BaseModel):
    id: int | None = None
    agent_run_id: int
    summary: str = ""
    risk_score: float = 0.0
    thesis: str = ""
    evidence: list[dict] = Field(default_factory=list)
    tool_calls: list[dict] = Field(default_factory=list)
    disclaimer: str = "Not financial advice. On-chain data only. DYOR."
