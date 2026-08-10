from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage

from whaledecode.adapters.llm_graph.utils import trim_history

SYSTEM_PROMPT = """You are a blockchain intelligence analyst. Given an on-chain event:
1. Identify what happened (type, tokens, value).
2. Assess significance — is this smart money moving?
3. Call on-chain tools to gather more context if needed.
4. Output your analysis concisely.

You operate under strict rate limits. DO NOT use tools more than twice per analysis. Base your SMC thesis on the provided blockchain event if tools fail.

# ENTITY RULES (STRICT)
- NEVER write raw EVM hex addresses (0x...) in your analysis. Name the parties involved by their entity labels from # EVENT ENTITIES (e.g. "Binance 16", "Kraken Hot Wallet", "Unlabeled EOA") or by macro terms ("CEX Outflow", "Cold Storage").
- Describe the financial significance and market impact in plain English for professional traders.

# OUTPUT FORMAT (STRICT)
You MUST structure your analysis using entity labels only:

**Involved Entities:** {from_entity} -> {to_entity}

**Assessment**
{2-3 sentence assessment, using entity labels, of what happened and why it matters}

# DATA GROUNDING
You MUST use the entity labels and exact event data provided above.
Do NOT invent, hallucinate, or assume any wallet labels, token amounts, or USD values.
If a piece of data is not provided in the event payload or the tool responses, you MUST write 'N/A' or 'Data Unavailable'.
Never fabricate a transaction hash, block number, address, or value that is not present in the event payload or tool responses."""


def _entity_context(event: dict) -> str:
    """Render the resolved entity labels for the event into a prompt block.

    Enrichment happens upstream (InvestigationService) and lands on the event dict
    as from_entity/to_entity; this node only injects what is already there.
    """
    lines = [f"{side}_entity: {event.get(f'{side}_entity')}" for side in ("from", "to") if event.get(f"{side}_entity")]
    return "\n".join(lines)


def create_analysis_node(llm: BaseChatModel):
    async def analyze_event(state: dict) -> dict:
        # The event was injected into state["messages"] as the opening user turn
        # before this node ran. Pass the history through as-is so tool calls stay
        # paired with their tool responses — no manual re-injection of the event.
        history = trim_history(state.get("messages", []))
        entities = _entity_context(state.get("event_data", {}))
        prompt = SYSTEM_PROMPT
        if entities:
            prompt += f"\n\n# EVENT ENTITIES\n{entities}"
        result = await llm.ainvoke([SystemMessage(content=prompt), *history])
        return {"messages": [result], "summary": result.content}
    return analyze_event
