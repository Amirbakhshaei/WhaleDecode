from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from whaledecode.adapters.llm_graph.utils import extract_clean_json

REPORT_PROMPT = """Based on the investigation, produce a structured answer with:
- summary: a concise plain-text answer to the user's question
- risk_score: float 0.0-1.0 indicating risk level
- thesis: brief explanation of why this matters
- evidence: JSON array of supporting facts (each: {"fact": "...", "source": "..."})
- tool_calls: JSON array of tools used
- disclaimer: standard crypto disclaimer

Output as valid JSON with these exact keys."""


def create_chat_report_node(llm: BaseChatModel):
    async def generate_report(state: dict) -> dict:
        analysis = state.get("summary", "")
        msg = HumanMessage(content=f"Analysis to summarize:\n\n{analysis}")
        result = await llm.ainvoke([SystemMessage(content=REPORT_PROMPT), msg])
        report = extract_clean_json(result.content)
        return {
            "messages": [result],
            **report,
        }
    return generate_report
