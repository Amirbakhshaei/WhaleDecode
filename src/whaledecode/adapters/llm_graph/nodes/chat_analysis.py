from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

SYSTEM_PROMPT = """You are a blockchain intelligence analyst. Given a user question about wallets, tokens, or transactions:
1. Understand what the user is asking.
2. Call on-chain tools to gather relevant data.
3. If you need more context, call another tool.
4. When you have enough data, answer the question directly."""


def create_chat_analysis_node(llm: ChatOpenAI):
    async def analyze_chat(state: dict) -> dict:
        query = state["query"]
        msg = HumanMessage(content=f"User question: {query}")
        result = await llm.ainvoke([SystemMessage(content=SYSTEM_PROMPT), msg])
        return {"messages": [result], "summary": result.content}
    return analyze_chat
