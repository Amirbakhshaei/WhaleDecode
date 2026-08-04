"""Data gatherer: runs the two deterministic tools and summarizes into `gathered_context`.

Exactly ONE LLM invocation. Tool selection is decided in Python from the
raw_event fields (never by the LLM), so the run is bounded and deterministic —
this is what keeps a full graph run at exactly 2 LLM calls.
"""
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool

GATHER_PROMPT = """You are a data gatherer. Summarize the factual on-chain and market
context for the whale event below using ONLY the tool results provided. Do NOT invent
addresses, amounts, or prices. If a fact is missing, state it is unavailable. Output a
concise, structured summary to hand off to the SMC analyst."""  # noqa: E501


def create_data_gatherer_node(llm: BaseChatModel, tools: list[BaseTool]):
    name_to_tool = {t.name: t for t in tools}

    async def _call_tool(tool_name: str, kwargs: dict) -> str:
        t = name_to_tool.get(tool_name)
        if t is None:
            return ""
        result = await t.ainvoke(kwargs)
        return result if isinstance(result, str) else str(result)

    async def data_gatherer(state: dict) -> dict:
        event = state.get("raw_event") or {}
        chain = event.get("chain", "ETH")

        # Deterministic tool dispatch based on the event's fields — no LLM routing.
        calls: list[str] = []
        if event.get("tx_hash"):
            calls.append(await _call_tool("etherscan_tool", {"tx_hash": event["tx_hash"], "chain": chain}))
        if token_address := _token_address(event):
            calls.append(await _call_tool("dexscreener_tool", {"token_address": token_address, "chain": chain}))

        tool_text = "\n\n".join(calls) or "No tool data could be gathered for this event."
        result = await llm.ainvoke(
            [
                SystemMessage(content=GATHER_PROMPT),
                HumanMessage(content=f"Event:\n{event}\n\nTool results:\n{tool_text}"),
            ]
        )
        return {"gathered_context": f"Tool results:\n{tool_text}\n\nSummary:\n{result.content}"}

    return data_gatherer


def _token_address(event: dict) -> str | None:
    for key in ("token_address", "token", "tokenAddress"):
        value = event.get(key)
        if value:
            return str(value)
    raw = event.get("raw_json") or {}
    for key in ("token_address", "token", "tokenAddress"):
        value = raw.get(key)
        if value:
            return str(value)
    return None
