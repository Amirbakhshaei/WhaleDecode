from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage

from whaledecode.adapters.llm_graph.utils import trim_history

SYSTEM_PROMPT = """You are a blockchain intelligence analyst. Given a user question about wallets, tokens, or transactions:
1. Understand what the user is asking.
2. Call on-chain tools to gather relevant data.
3. If you need more context, call another tool.
4. When you have enough data, answer the question directly."""


def create_chat_analysis_node(llm: BaseChatModel):
    async def analyze_chat(state: dict) -> dict:
        # The user's question was injected into state["messages"] as the opening
        # user turn before this node ran — pass the history through as-is.
        history = trim_history(state.get("messages", []))
        result = await llm.ainvoke([SystemMessage(content=SYSTEM_PROMPT), *history])
        return {"messages": [result], "summary": result.content}
    return analyze_chat
