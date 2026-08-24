import json

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from whaledecode.adapters.llm_graph.utils import trim_history
from whaledecode.domain.schemas.llm_outputs import EventAnalysisResult


def build_synthesis_prompt(event_data: dict) -> str:
    """Build a fully self-contained Tier 1 synthesis prompt.

    All verified on-chain facts are inlined as a structured block so the LLM
    needs no external lookups to reason about the transaction."""
    raw = event_data.get("raw_json") if isinstance(event_data.get("raw_json"), dict) else {}
    chain = event_data.get("chain") or raw.get("chain") or "Unknown"
    asset = event_data.get("asset") or raw.get("symbol") or raw.get("token") or "Unknown Token"
    value = event_data.get("total_value_usd") or event_data.get("value_usd") or raw.get("value_usd") or 0.0
    try:
        value_fmt = f"${float(value):,.2f}"
    except (TypeError, ValueError):
        value_fmt = "$0.00"
    from_label = event_data.get("from_label") or "Unknown Wallet"
    to_label = event_data.get("to_label") or "Unknown Wallet"
    from_category = event_data.get("from_category") or "Unlabeled"
    to_category = event_data.get("to_category") or "Unlabeled"
    from_addr = str(event_data.get("from_address") or raw.get("from") or "")
    to_addr = str(event_data.get("to_address") or raw.get("to") or "")
    flow_type = event_data.get("flow_type") or event_data.get("event_category") or "Unknown"
    sender_tx = event_data.get("sender_tx_count_30d") or raw.get("tx_count_30d") or event_data.get("tx_count_30d") or 0
    return f"""You are a quantitative on-chain intelligence analyst.
Analyze the transaction strictly based on the verified on-chain parameters below.

STRICT RULES:
1. ZERO RAW HEX ADDRESSES (0x...) or hashes in your analysis. Use resolved entity labels or macro terms.
2. NEVER invent off-chain orderbook mechanics or liquidity depth (do not claim "cleared orderbooks" for wallet transfers).
3. Clearly classify the flow:
   - CEX Outflow (Exchange -> Wallet): Spot accumulation / custody withdrawal.
   - CEX Inflow (Wallet -> Exchange): Sell preparation / liquidity provision.
   - Internal Rebalancing (Exchange -> Exchange): Neutral exchange infrastructure maintenance.
   - Smart Money Transfer (Whale -> Whale): Strategic OTC or treasury movement.
4. Base every number ONLY on the data block below. Never fabricate percentages, price levels, or volume figures.
5. NEVER output brackets ('[', ']'), plus signs ('+'), or 'N/A'. Reason qualitatively if a figure is absent.

OUTPUT (respond with a valid JSON object, exactly these four fields — the runtime enforces the schema):
- entity_profile: 1 sentence stating the attribution flow and behavioral archetype.
- context: 1 sentence on market context, execution timing, or volume magnitude.
- impact: 1 sentence on supply shock, orderbook drain, or directional buy/sell bias.
- conviction_score: integer 0-100 confidence based on entity quality and volume.

TRANSACTION DATA:
- Chain: {chain}
- Asset: {asset}
- Total Value USD: {value_fmt}
- Sender: {from_label} ({from_category}) [{from_addr[:10]}...]
- Receiver: {to_label} ({to_category}) [{to_addr[:10]}...]
- Flow Classification: {flow_type}
- Historical Activity (30d): {sender_tx} txs
"""


def _render_price_levels(levels) -> str:
    """Render 24h/7d/30d high-low + recent daily closes as one compact block."""
    if not levels or not isinstance(levels, dict):
        return "Unavailable"

    def _hl(name: str) -> str:
        bucket = levels.get(name)
        if not isinstance(bucket, dict) or not bucket.get("high") or not bucket.get("low"):
            return "N/A"
        return f"{bucket['high']:,.4f} / {bucket['low']:,.4f}"

    closes = levels.get("daily_closes") or []
    closes_text = ", ".join(f"{c:,.4f}" for c in closes[:5]) if closes else "N/A"
    return (
        f"24h High/Low: {_hl('24h')}\n"
        f"7d High/Low: {_hl('7d')}\n"
        f"30d High/Low: {_hl('30d')}\n"
        f"Daily Closes (5): {closes_text}"
    )


def create_analysis_node(llm: BaseChatModel):
    structured_llm = llm.with_structured_output(EventAnalysisResult)

    async def analyze_event(state: dict) -> dict:
        # The event was injected into state["messages"] as the opening user turn
        # before this node ran. Pass the history through as-is so tool calls stay
        # paired with their tool responses — no manual re-injection of the event.
        history = trim_history(state.get("messages", []))
        prompt = build_synthesis_prompt(state.get("event_data", {}))
        levels = _render_price_levels(state.get("event_data", {}).get("price_levels"))
        if levels != "Unavailable":
            prompt += f"\n\n# KEY PRICE LEVELS (USD, cite these)\n{levels}"
        result: EventAnalysisResult = await structured_llm.ainvoke(
            [SystemMessage(content=prompt), *history]
        )
        # Re-serialize to the JSON string the consolidated report consumes as text,
        # so the downstream contract is unchanged while the source parse is now guaranteed.
        summary = json.dumps(result.model_dump())
        return {"messages": [AIMessage(content=summary)], "summary": summary}
    return analyze_event
