"""Single-call consolidated node: report + score + guardrails + format in one LLM invocation."""
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from whaledecode.adapters.llm_graph.state.investigation_result import InvestigationResult

SYSTEM_PROMPT = """You are a blockchain intelligence analyst. Given the analysis of an on-chain event, produce a single structured investigation result with:
- thesis: your core investment or risk thesis
- evidence: JSON array of supporting facts (each: {"fact": "...", "source": "..."})
- risk_score: float 0.0-1.0
- is_safe: true if the event passes all safety guardrails, false otherwise
- briefing_markdown: the final Telegram briefing, MUST strictly follow the EXACT template below
- disclaimer: standard crypto disclaimer, extended with a HIGH RISK warning if risk_score > 0.95

briefing_markdown template (fill placeholders with event/tool data ONLY, wrap every hash/address in ||...|| spoiler tags so they are hidden, '>' for the Intelligence blockquote):
🫧 **[Event Type]**
💎 **Value:** `$[USD Value]` [Token]
🌐 **Chain:** [Chain]
🎯 **Risk:** [Score]%

> **🧠 SMC Intelligence**
> Emit short, punchy bullet points, each one per line with a keyword and ':' —
> • **Action:** [what moved and the flow direction]
> • **Context:** [structural/liquidity significance]
> • **Bias:** [market-structure read: short/neutral/long]
> No filler words, no preamble, no trailing prose.

**Trace Metrics**
Tx: ||`[tx_hash]`||
From: ||`[from_address]`||
To: ||`[to_address]`||

FORMATTING RULES:
1. Combine the SMC thesis into SHORT, punchy bullets (Action/Context/Bias), one per line.
2. Format numbers with commas.
3. Enclose all transaction hashes and addresses inside Telegram spoiler tags exactly like this: ||`0x...`|| so they are hidden.
4. Use the `>` character at the beginning of the line to create a blockquote for the Intelligence section.

DATA GROUNDING:
- Every placeholder comes from the event payload or tool results ONLY.
- Do NOT invent, hallucinate, or assume any wallet addresses, token amounts, or USD values.
- If a piece of data is not provided or a tool returned an ERROR, use `[ N/A ]` — never a made-up number.

Output strictly as JSON matching the schema exactly."""


def create_consolidated_report_node(llm: BaseChatModel):
    structured_llm = llm.with_structured_output(InvestigationResult)

    async def consolidated_report(state: dict) -> dict:
        event = state.get("event_data", {})
        analysis = state.get("summary", "")
        tool_calls = _collect_tool_calls(state.get("messages", []))
        msg = HumanMessage(content=f"Event:\n{event}\n\nAnalysis:\n{analysis}")
        result: InvestigationResult = await structured_llm.ainvoke(
            [SystemMessage(content=SYSTEM_PROMPT), msg]
        )
        return {
            "messages": [msg],
            "thesis": result.thesis,
            "evidence": result.evidence,
            "risk_score": result.risk_score,
            "is_safe": result.is_safe,
            "summary": result.briefing_markdown,
            "disclaimer": result.disclaimer,
            "tool_calls": tool_calls,
        }

    return consolidated_report


def _collect_tool_calls(messages: list) -> list[dict]:
    """Extract executed tool calls from the message history."""
    calls = []
    for msg in messages:
        for call in getattr(msg, "tool_calls", []) or []:
            calls.append({"name": call.get("name", ""), "args": call.get("args", {})})
    return calls
