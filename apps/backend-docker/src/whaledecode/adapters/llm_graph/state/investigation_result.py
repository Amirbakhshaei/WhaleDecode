"""Unified schema for consolidated investigation output."""
from pydantic import BaseModel, Field, field_validator


class InvestigationResult(BaseModel):
    """Single-call structured output capturing all investigation artifacts."""

    thesis: str = Field(
        description="The core investment or risk thesis, grounded ONLY in the tool/on-chain data provided. "
        "Do NOT invent wallet addresses, amounts, or USD values."
    )
    fundamental_summary: str = Field(
        default="",
        description=(
            "Institutional-trade-grade fundamental analysis. Format: "
            "[Vector: CEX Outflow/Inflow/Inter-Exchange] + [Entity Route] + [Supply Impact / % of 24h Volume or Liquid Depth]. "
            "ZERO raw 0x hex addresses. Use resolved entity labels (e.g., 'Binance 16', 'Unlabeled Cold Wallet'). "
            "Do NOT repeat basic transfer metrics; provide market context."
        ),
    )
    technical_summary: str = Field(
        default="",
        description=(
            "Institutional-trade-grade technical analysis. Format: "
            "[Interaction with Key Price Levels / VWAP / Support / Resistance] + [Orderbook Impact (e.g., Absorption, Liquidity Sweep)]. "
            "ZERO raw 0x hex addresses. Use entity labels and market terms only."
        ),
    )
    bias_summary: str = Field(
        default="",
        description=(
            "Institutional-trade-grade directional read. Format: "
            "[Directional Bias: Bullish Accumulation / Bearish Distribution / Neutral Rebalancing] + "
            "[Actionable Trigger or Invalidation Level]. ZERO raw 0x hex addresses."
        ),
    )
    evidence: list[dict] = Field(
        description="List of factual evidence points, each with 'fact' and 'source'. "
        "Every figure must come from tool output; no fabricated data."
    )
    risk_score: float = Field(
        description=(
            "Conviction/impact score on the FULL 0.0-1.0 scale (equal to a 0-100 score). "
            "USE THE ENTIRE RANGE - never cluster around 0.5 as a safe default. "
            "This score gates publishing (per-chain floor 65-75), so under-scoring suppresses valid alerts. "
            "MANDATORY ANCHORS: (1) total_value_usd >= 5000000 AND flow_type == 'CEX Outflow' (incl. cold-storage "
            "accumulation) or a $5M+ high-impact DEX liquidity drain -> score >= 0.80. "
            "(2) total_value_usd >= 1000000 AND flow_type == 'CEX Outflow' -> score >= 0.68. "
            "(3) flow_type == 'Inter-Exchange Transfer' (CEX internal) -> score <= 0.35 regardless of value. "
            "Between anchors: 0.65-0.79 smart money / significant flows ($1M-$4.999M directional, LP sweeps, "
            "smart-money accumulation campaigns); 0.40-0.64 routine directional transfers ($50k-$999k); "
            "below 0.40 zero-signal noise (CEX hot-wallet rotations, MEV/dust, unlabeled)."
        ),
        ge=0.0,
        le=1.0,
    )

    @field_validator("risk_score", mode="before")
    @classmethod
    def _normalize_risk_score(cls, value) -> float:
        value = float(value)
        if value > 1.0:
            value /= 100.0
        return max(0.0, min(1.0, value))
    is_safe: bool = Field(
        description="True if the event passes all safety guardrails."
    )
    briefing_markdown: str = Field(
        description=(
            "The final briefing in standard Markdown.\n"
            "Instructions:\n"
            "1. Combine the SMC thesis into a SINGLE, dense paragraph.\n"
            "2. Format numbers with commas.\n"
            "3. Enclose all transaction hashes and addresses inside Telegram spoiler tags exactly like this: ||`0x...`|| so they are hidden.\n\n"
            "🫧 **[Event Type]**\n"
            "💎 **Value:** `$[USD Value]` [Token]\n"
            "🌐 **Chain:** [Chain]\n"
            "🎯 **Risk:** [Score]%\n\n"
            "> **🧠 SMC Intelligence**\n"
            "> [Write a dense 1-2 sentence paragraph stating exactly what moved and its structural/liquidity significance. No filler words. Name counterparties by entity label (e.g. 'Binance 16', 'Unlabeled EOA') or macro terms — never raw 0x addresses.]\n\n"
            "**Trace Metrics**\n"
            "Tx: ||`[tx_hash]`||\n"
            "From: ||`[from_address]`||\n"
            "To: ||`[to_address]`||"
        )
    )
    disclaimer: str = Field(
        description="Standard crypto disclaimer with risk-specific notes."
    )
