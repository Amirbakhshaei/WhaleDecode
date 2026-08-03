from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage

from whaledecode.adapters.llm_graph.utils import trim_history

SYSTEM_PROMPT = """You are a blockchain intelligence analyst. Given an on-chain event:
1. Identify what happened (type, tokens, value).
2. Assess significance — is this smart money moving?
3. Call on-chain tools to gather more context if needed.
4. Output your analysis concisely.

You operate under strict rate limits. DO NOT use tools more than twice per analysis. Base your SMC thesis on the provided blockchain event if tools fail.

# OUTPUT FORMAT (STRICT)
You MUST return the `summary` field formatted exactly like this:

**On-Chain Analysis — {event_type}**

**Network:** {chain}
**Transaction:** {tx_hash}
**Block:** {block_number}
**Involved Addresses:** {from_address} -> {to_address}
**Token / Amount:** {amount} {token}
**USD Value:** ${value_usd}

**Assessment**
{2-3 sentence assessment of what happened and why it matters}

# DATA GROUNDING
You MUST use the exact formatting template provided above.
Do NOT invent, hallucinate, or assume any wallet addresses, token amounts, or USD values.
If a piece of data is not provided in the event payload or the tool responses, you MUST write 'N/A' or 'Data Unavailable'.
Never fabricate a transaction hash, block number, address, or value that is not present in the event payload or tool responses."""


def create_analysis_node(llm: BaseChatModel):
    async def analyze_event(state: dict) -> dict:
        # The event was injected into state["messages"] as the opening user turn
        # before this node ran. Pass the history through as-is so tool calls stay
        # paired with their tool responses — no manual re-injection of the event.
        history = trim_history(state.get("messages", []))
        result = await llm.ainvoke([SystemMessage(content=SYSTEM_PROMPT), *history])
        return {"messages": [result], "summary": result.content}
    return analyze_event
