from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

SYSTEM_PROMPT = """You are a blockchain intelligence analyst. Given an on-chain event:
1. Identify what happened (type, tokens, value).
2. Assess significance — is this smart money moving?
3. Call on-chain tools to gather more context if needed.
4. Output your analysis concisely."""


def create_analysis_node(llm: ChatOpenAI):
    async def analyze_event(state: dict) -> dict:
        event = state["event_data"]
        msg = HumanMessage(content=f"Investigate this on-chain event:\n\n{event}")
        result = await llm.ainvoke([SystemMessage(content=SYSTEM_PROMPT), msg])
        return {"messages": [result], "summary": result.content}
    return analyze_event
