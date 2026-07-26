from typing import Any


class EventResult:
    summary: str
    risk_score: float
    thesis: str
    evidence: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    disclaimer: str
    latency_ms: int


class EventListResult:
    events: list[dict[str, Any]]
    total: int
