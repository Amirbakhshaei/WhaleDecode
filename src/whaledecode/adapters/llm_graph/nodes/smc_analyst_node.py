"""SMC analyst: turns raw_event + gathered_context into a Telegram-ready brief.

NO tools and exactly ONE LLM invocation. Pure reasoning node: every figure in the
brief must come from gathered_context / raw_event, never invented.
"""
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

SMC_SYSTEM_PROMPT = """You are a Smart Money Concepts (SMC) blockchain analyst.
Analyze the whale event below using ONLY the provided on-chain and market context.
Produce a Telegram-ready markdown brief following this EXACT template:

🫧 **[Event Type]**
💎 **Value:** `$[USD Value]` [Token]
🌐 **Chain:** [Chain]
🎯 **Risk:** [Score]%

> **🧠 SMC Intelligence**
> Emit exactly three punchy bullet lines, each starting with a keyword and colon:
> • *Action:* [one line: what moved, from where to where, approximate USD flow]
> • *Context:* [one line: structural/liquidity significance of the move]
> • *Bias:* [one line: short/neutral/long read on market structure implications]
> No filler words, no preamble, no trailing prose.

**Trace Metrics**
Tx: ||`[tx_hash]`||
From: ||`[from_address]`||
To: ||`[to_address]`||

RULES:
1. Every address and hash inside Telegram spoiler tags: ||`0x...`||.
2. Base every number ONLY on the context provided. Missing data reads '[ N/A ]'.
3. Do NOT invent wallet addresses, token amounts, or USD values.
4. Format numbers with commas."""  # noqa: E501


def create_smc_analyst_node(llm: BaseChatModel):
    async def smc_analyst(state: dict) -> dict:
        event = state.get("raw_event") or {}
        context = state.get("gathered_context", "")
        result = await llm.ainvoke(
            [
                SystemMessage(content=SMC_SYSTEM_PROMPT),
                HumanMessage(content=f"Event:\n{event}\n\nGathered context:\n{context}"),
            ]
        )
        return {"final_thesis": result.content}

    return smc_analyst
