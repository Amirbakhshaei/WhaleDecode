"""Unified schema for consolidated investigation output."""
from pydantic import BaseModel, Field


class InvestigationResult(BaseModel):
    """Single-call structured output capturing all investigation artifacts."""

    thesis: str = Field(description="The core investment or risk thesis.")
    evidence: list[dict] = Field(
        description="List of factual evidence points, each with 'fact' and 'source'."
    )
    risk_score: float = Field(
        description="Risk score between 0.0 and 1.0.", ge=0.0, le=1.0
    )
    is_safe: bool = Field(
        description="True if the event passes all safety guardrails."
    )
    briefing_markdown: str = Field(
        description="The final formatted Telegram briefing in Markdown."
    )
    disclaimer: str = Field(
        description="Standard crypto disclaimer with risk-specific notes."
    )
