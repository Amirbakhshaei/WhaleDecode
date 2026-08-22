"""Pydantic schemas for structured LLM outputs.

Using ``BaseChatModel.with_structured_output`` instead of hand-rolled
``json.loads``/regex parsing removes the schema-drift class of bugs (a model
emitting prose or slightly-off JSON that a downstream formatter then chokes on).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatReportResult(BaseModel):
    """Structured answer produced by the chat investigation report node.

    Field names mirror the keys the chat formatters read off the report dict
    (``summary``, ``risk_score``, ``thesis``, ``evidence``, ``tool_calls``,
    ``disclaimer``), so swapping ``extract_clean_json`` for this keeps every
    downstream consumer working unchanged.
    """

    summary: str = Field(..., description="Concise plain-text answer to the user's question.")
    risk_score: float = Field(
        default=0.5,
        description="Risk level as a float between 0.0 and 1.0.",
    )
    thesis: str = Field(default="", description="Brief explanation of why this matters.")
    evidence: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Supporting facts, each a dict with 'fact' and 'source'.",
    )
    tool_calls: list[Any] = Field(
        default_factory=list,
        description="Tools used during the investigation.",
    )
    disclaimer: str = Field(
        default="Not financial advice.",
        description="Standard crypto disclaimer.",
    )


class EventAnalysisResult(BaseModel):
    """Structured per-event analysis produced by the event analysis node.

    The model is constrained via ``with_structured_output`` so the four fields
    are guaranteed well-formed — no reliance on the LLM spontaneously emitting
    parseable JSON that a downstream formatter then has to recover.
    """

    entity_profile: str = Field(
        ...,
        description=(
            "1 concise sentence describing the wallet entity and behavioral "
            "archetype (e.g., Binance Hot Wallet -> Institutional Accumulator)."
        ),
    )
    context: str = Field(
        ...,
        description="1 concise sentence detailing market context, execution timing, or volume magnitude.",
    )
    impact: str = Field(
        ...,
        description="1 concise sentence evaluating supply shock, exchange liquid reserves depletion, or directional bias.",
    )
    conviction_score: int = Field(
        default=75,
        ge=0,
        le=100,
        description="Confidence/conviction score between 0 and 100 based on entity quality and volume.",
    )
