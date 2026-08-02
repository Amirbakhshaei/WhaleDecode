from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage

from whaledecode.adapters.llm_graph.utils import trim_history

SYSTEM_PROMPT = """You are a blockchain intelligence analyst. Given an on-chain event:
1. Identify what happened (type, tokens, value).
2. Assess significance — is this smart money moving?
3. Call on-chain tools to gather more context if needed.
4. Output your analysis concisely."""


def create_analysis_node(llm: BaseChatModel):
    async def analyze_event(state: dict) -> dict:
        # The event was injected into state["messages"] as the opening user turn
        # before this node ran. Pass the history through as-is so tool calls stay
        # paired with their tool responses — no manual re-injection of the event.
        history = trim_history(state.get("messages", []))
        result = await llm.ainvoke([SystemMessage(content=SYSTEM_PROMPT), *history])
        return {"messages": [result], "summary": result.content}
    return analyze_event
