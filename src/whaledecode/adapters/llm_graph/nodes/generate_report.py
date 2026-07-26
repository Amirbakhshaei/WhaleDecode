from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

REPORT_PROMPT = """Based on the analysis, produce a structured investigation report with:
- summary: one-line plain text
- risk_score: float 0.0–1.0
- thesis: your investment thesis
- evidence: JSON array of supporting facts (each: {{"fact": "...", "source": "..."}})
- tool_calls: JSON array of tools used
- disclaimer: standard crypto disclaimer

Output as valid JSON with these exact keys."""


def create_report_node(llm: ChatOpenAI):
    async def generate_report(state: dict) -> dict:
        analysis = state.get("summary", "")
        msg = HumanMessage(content=f"Analysis to summarize:\n\n{analysis}")
        result = await llm.ainvoke([SystemMessage(content=REPORT_PROMPT), msg])
        import json
        try:
            report = json.loads(result.content)
        except (json.JSONDecodeError, TypeError):
            report = {"summary": result.content, "risk_score": 0.5, "thesis": "", "evidence": [], "tool_calls": [], "disclaimer": "Not financial advice."}
        return {
            "messages": [result],
            **report,
        }
    return generate_report
