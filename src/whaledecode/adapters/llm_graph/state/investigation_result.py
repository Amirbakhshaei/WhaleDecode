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
            "The final Telegram briefing. YOU MUST STRICTLY USE THIS EXACT MARKDOWN TEMPLATE. "
            "Use backticks for hashes and addresses so they are tap-to-copy in Telegram:\n\n"
            "⚡ **[Event Type]** | `$[USD Value]`\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔹 **Network**: [Chain Name]\n"
            "🔹 **Amount**: `[Amount] [Token]`\n\n"
            "**🔗 Execution Details**\n"
            "• **TX**: `[tx_hash]`\n"
            "• **From**: `[from_address]`\n"
            "• **To**: `[to_address]`\n\n"
            "**🧠 Quantitative Assessment**\n"
            "[Write a concise, 2-3 sentence technical assessment of the event's significance, potential risk, and market impact.]\n\n"
            "If any data is missing or a tool fails, write 'Data Unavailable'. DO NOT hallucinate addresses or values."
        )
    )
    disclaimer: str = Field(
        description="Standard crypto disclaimer with risk-specific notes."
    )
