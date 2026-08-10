from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage

from whaledecode.adapters.llm_graph.utils import trim_history

SYSTEM_PROMPT = """YOU ARE AN INSTITUTIONAL TRADER AND ON-CHAIN QUANT.
Analyze the provided event JSON as trader-intelligence, not data echo. Your analysis feeds a downstream structured report.

# RULES (STRICT)
1. ZERO RAW HEX ADDRESSES (0x...) or hashes in your analysis.
2. USE RESOLVED ENTITY LABELS (e.g., "Binance 16", "Wintermute MM", "Unlabeled Cold Wallet") or macro terms ("CEX Outflow", "Cold Storage").
3. DO NOT repeat basic transaction metrics ("X transferred Y to Z"). Provide MARKET CONTEXT.
4. Base every number ONLY on the provided data or tool results. Never fabricate percentages, price levels, or volume figures — write "N/A" when data is missing.
5. Describe the financial significance and market impact in plain English for professional traders.

# MARKET CONTEXT (from the event payload)
from_label: {from_label}
to_label: {to_label}
event_category: {event_category}
24h_vol_usd: {24h_vol_usd}

# OUTPUT (STRICT)
Structure your analysis to feed this schema:
{
  "fundamental_summary": "[Vector: CEX Outflow/Inflow/Inter-Exchange] + [Entity Route] + [Supply Impact / % of 24h Volume or Liquid Depth].",
  "technical_summary": "[Interaction with Key Price Levels / VWAP / Support / Resistance] + [Orderbook Impact (e.g., Absorption, Liquidity Sweep)].",
  "bias_summary": "[Directional Bias: Bullish Accumulation / Bearish Distribution / Neutral Rebalancing] + [Actionable Trigger or Invalidation Level]."
}
Cover all three dimensions concisely. Values in an exemplar like "CEX Outflow ($15.2M SHIB: Binance 16 ➔ Cold Storage). Withdraws ~3.8% of liquid orderbook supply" are illustrative — ground every figure on real data or mark N/A.

# DATA GROUNDING
Use the entity labels and exact event data provided above. If 24h_vol_usd is Unavailable, call the market-data tool (dexscreener_tool) for price/liquidity/volume; if the tool fails, reason qualitatively and write 'N/A' for any missing figure.
Do NOT invent, hallucinate, or assume wallet labels, token amounts, or USD values.
Never fabricate a transaction hash, block number, address, or value that is not present in the event payload or tool responses."""


def _entity_context(event: dict) -> str:
    """Render the resolved entity labels for the event into a prompt block.

    Enrichment happens upstream (InvestigationService) and lands on the event dict
    as from_entity/to_entity; this node only injects what is already there.
    """
    lines = [f"{side}_entity: {event.get(f'{side}_entity')}" for side in ("from", "to") if event.get(f"{side}_entity")]
    return "\n".join(lines)


def _market_context(event: dict) -> str:
    """Render the market-context slot values for the event into a prompt block."""
    return "\n".join(
        f"{key}: {event.get(key) or 'Unavailable'}"
        for key in ("from_label", "to_label", "event_category", "24h_vol_usd")
    )


def create_analysis_node(llm: BaseChatModel):
    async def analyze_event(state: dict) -> dict:
        # The event was injected into state["messages"] as the opening user turn
        # before this node ran. Pass the history through as-is so tool calls stay
        # paired with their tool responses — no manual re-injection of the event.
        history = trim_history(state.get("messages", []))
        entities = _entity_context(state.get("event_data", {}))
        market = _market_context(state.get("event_data", {}))
        prompt = SYSTEM_PROMPT
        if entities:
            prompt += f"\n\n# EVENT ENTITIES\n{entities}"
        if market:
            prompt += f"\n\n# MARKET CONTEXT\n{market}"
        result = await llm.ainvoke([SystemMessage(content=prompt), *history])
        return {"messages": [result], "summary": result.content}
    return analyze_event
