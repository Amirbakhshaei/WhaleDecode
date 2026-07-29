from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


class ChatInvestigationState(TypedDict):
    query: str
    messages: Annotated[list, add_messages]
    summary: str
    risk_score: float
    thesis: str
    evidence: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    disclaimer: str
