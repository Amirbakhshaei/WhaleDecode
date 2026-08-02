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
            "Instructions:\n"
            "1. Format the USD value with commas and zero decimals (e.g., $150,000).\n"
            "2. Convert event types to Title Case (e.g., 'High Value Transfer' instead of HIGHVALUETRANSFER).\n"
            "3. If data is missing, output `[ N/A ]` instead of 'Data Unavailable'.\n"
            "4. The Assessment MUST be written through the lens of Smart Money Concepts (SMC), analyzing liquidity, market structure, or institutional order flow. Keep it to 2 concise sentences.\n\n"
            "🚨 **WHALE DECODE: ON-CHAIN ALERT**\n\n"
            "**Event:** `[Event Type]`\n"
            "**Value:** `$[USD Value]`\n"
            "**Chain:** `[Network]`\n\n"
            "📊 **Execution Details**\n"
            "├ **Hash:** `[tx_hash]`\n"
            "├ **Sender:** `[from_address]`\n"
            "└ **Receiver:** `[to_address]`\n\n"
            "🧠 **SMC Assessment**\n"
            "[Your Smart Money analysis here.]"
        )
    )
    disclaimer: str = Field(
        description="Standard crypto disclaimer with risk-specific notes."
    )
