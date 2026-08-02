from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


class EventInvestigationState(TypedDict):
    event_data: dict[str, Any]
    messages: Annotated[list, add_messages]
    summary: str
    risk_score: float
    is_safe: bool
    thesis: str
    evidence: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    disclaimer: str
