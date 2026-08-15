from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from whaledecode.adapters.llm_graph.utils import trim_history

SYSTEM_PROMPT = """YOU ARE THE WHALEDECODE ON-CHAIN REASONING AGENT.
Analyze the provided transaction data and telemetry as trader-intelligence, not data echo.

# RULES (STRICT)
1. ZERO RAW HEX ADDRESSES (0x...) or hashes in your analysis.
2. USE RESOLVED ENTITY LABELS (e.g., "Binance 16", "Wintermute MM", "Unlabeled Cold Wallet") or macro terms ("CEX Outflow", "Cold Storage").
3. DO NOT repeat basic transaction metrics ("X transferred Y to Z"). Provide MARKET CONTEXT.
4. Base every number ONLY on the provided data or tool results. Never fabricate percentages, price levels, or volume figures — write "N/A" when data is missing.
5. Describe the financial significance and market impact in plain English for professional traders.

# OUTPUT (STRICT JSON — NON-NEGOTIABLE)
You MUST respond ONLY with valid JSON matching these EXACT keys. No other keys, no extra prose:

{
  "entity_profile": "1-sentence attribution: [From Entity] -> [To Entity] with wallet archetype (e.g. Fresh Accumulator, MM Rebalancing).",
  "context": "1-sentence market context: Execution timing, volume magnitude, or protocol interaction.",
  "impact": "1-sentence market consequence: Supply shock, orderbook drain, or directional buy/sell bias."
}

CRITICAL: Do not wrap in markdown blocks. Output raw JSON only.

# MARKET CONTEXT (from the event payload)
from_label: {from_label}
to_label: {to_label}
event_category: {event_category}
24h_vol_usd: {24h_vol_usd}
asset: {asset}
token_amount_formatted: {token_amount_formatted}
total_value_usd: {total_value_usd}
price_at_timestamp: {price_at_timestamp}
chain: {chain}
flow_type: {flow_type}

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


def prepare_llm_context(event: dict) -> dict:
    """Build the exact-amount + price-level facts the LLM must anchor on.

    Every field comes from the enriched event payload (stamped by
    InvestigationService) or the raw RPC log — never fabricated. Values are
    rendered for human reading so the LLM quotes them verbatim instead of
    guessing from memory. Deliberately lean: high/low levels only, no raw
    candle dumps.
    """
    raw = event.get("raw_json") if isinstance(event.get("raw_json"), dict) else {}
    token_amount = event.get("token_amount")
    if token_amount is None:
        token_amount = _first_present(raw, ("token_amount", "amount"))
    asset = event.get("asset") or raw.get("symbol") or raw.get("token") or "Unknown Token"
    value_usd = event.get("total_value_usd")
    if value_usd is None:
        value_usd = _first_present(raw, ("value_usd", "total_value_usd"))
    price_at = event.get("price_at_timestamp")

    def _fmt(value, fmt):
        try:
            return fmt(float(value))
        except (TypeError, ValueError):
            return "Unavailable"

    levels_text = _render_price_levels(event.get("price_levels"))
    return {
        "asset": asset,
        "token_amount_formatted": _fmt(token_amount, lambda v: f"{v:,.4f}"),
        "total_value_usd": _fmt(value_usd, lambda v: f"${v:,.0f}"),
        "price_at_timestamp": _fmt(price_at, lambda v: f"${v:,.6f}"),
        "chain": event.get("chain") or raw.get("chain") or "Unknown",
        "flow_type": event.get("flow_type") or event.get("event_category") or "Unknown",
        "key_price_levels": levels_text,
    }


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


def _first_present(raw: dict, keys: tuple[str, ...]):
    for key in keys:
        value = raw.get(key)
        if value is not None and value != "":
            return value
    return None


def create_analysis_node(llm: BaseChatModel):
    async def analyze_event(state: dict) -> dict:
        # The event was injected into state["messages"] as the opening user turn
        # before this node ran. Pass the history through as-is so tool calls stay
        # paired with their tool responses — no manual re-injection of the event.
        history = trim_history(state.get("messages", []))
        entities = _entity_context(state.get("event_data", {}))
        market = _market_context(state.get("event_data", {}))
        exact = prepare_llm_context(state.get("event_data", {}))
        levels = exact.pop("key_price_levels", "Unavailable")
        prompt = SYSTEM_PROMPT
        if entities:
            prompt += f"\n\n# EVENT ENTITIES\n{entities}"
        if market:
            prompt += f"\n\n# MARKET CONTEXT\n{market}"
        prompt += "\n\n# EXACT AMOUNTS (cite these verbatim)\n" + "\n".join(
            f"{key}: {value}" for key, value in exact.items()
        )
        prompt += f"\n\n# KEY PRICE LEVELS (USD, cite these)\n{levels}"
        result = await llm.ainvoke([SystemMessage(content=prompt), *history])
        return {"messages": [result], "summary": result.content}
    return analyze_event
