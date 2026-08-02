"""Unified schema for consolidated investigation output."""
from pydantic import BaseModel, Field


class InvestigationResult(BaseModel):
    """Single-call structured output capturing all investigation artifacts."""

    thesis: str = Field(
        description="The core investment or risk thesis, grounded ONLY in the tool/on-chain data provided. "
        "Do NOT invent wallet addresses, amounts, or USD values."
    )
    evidence: list[dict] = Field(
        description="List of factual evidence points, each with 'fact' and 'source'. "
        "Every figure must come from tool output; no fabricated data."
    )
    risk_score: float = Field(
        description="Risk score between 0.0 and 1.0.", ge=0.0, le=1.0
    )
    is_safe: bool = Field(
        description="True if the event passes all safety guardrails."
    )
    briefing_markdown: str = Field(
        description=(
            "The final Telegram briefing. YOU MUST STRICTLY USE THIS EXACT MARKDOWN TEMPLATE:\n"
            "🚨 [Risk Level]: [Event Type] 🚨\n\n"
            "**TX:** `[tx_hash]`\n"
            "**Value:** $[USD Value]\n\n"
            "**Analysis:**\n"
            "- [Bullet 1]\n"
            "- [Bullet 2]\n\n"
            "Every placeholder comes from the event payload or tool results ONLY. "
            "If the tools return no data or fail, write 'DATA UNAVAILABLE'. "
            "DO NOT hallucinate addresses, amounts, or USD values."
        )
    )
    disclaimer: str = Field(
        description="Standard crypto disclaimer with risk-specific notes."
    )
