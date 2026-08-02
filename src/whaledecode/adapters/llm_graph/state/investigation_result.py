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
            "The final Telegram briefing. YOU MUST STRICTLY USE THIS EXACT MARKDOWN TEMPLATE.\n"
            "Instructions:\n"
            "1. Combine the factual summary and SMC thesis into a SINGLE, dense 2-sentence paragraph.\n"
            "2. Format numbers with commas (e.g., $150,000).\n"
            "3. If data is missing, use `[ N/A ]`.\n"
            "4. Use the `>` character at the beginning of the line to create a blockquote for the Intelligence section.\n\n"
            "✦ *[Event Type]*\n"
            "`$[USD Value]` · `[Amount] [Token]` · [Chain]\n"
            "Risk Score: [Score]%\n\n"
            "> **Intelligence**\n"
            "> [Write a dense 1-2 sentence paragraph stating exactly what moved and its structural/liquidity significance (SMC). No filler words.]\n\n"
            "**Trace**\n"
            "Tx: `[tx_hash]`\n"
            "From: `[from_address]`\n"
            "To: `[to_address]`"
        )
    )
    disclaimer: str = Field(
        description="Standard crypto disclaimer with risk-specific notes."
    )
