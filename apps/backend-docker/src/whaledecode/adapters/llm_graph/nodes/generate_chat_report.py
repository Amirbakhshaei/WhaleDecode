from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from whaledecode.domain.schemas.llm_outputs import ChatReportResult

REPORT_PROMPT = """Based on the investigation, produce a structured answer with:
- summary: a concise plain-text answer to the user's question
- risk_score: float 0.0-1.0 indicating risk level
- thesis: brief explanation of why this matters
- evidence: JSON array of supporting facts (each: {"fact": "...", "source": "..."})
- tool_calls: JSON array of tools used
- disclaimer: standard crypto disclaimer

DATA GROUNDING: Do NOT invent, hallucinate, or assume wallet addresses, amounts, or USD values. Base every figure ONLY on the analysis provided. Missing data reads "N/A" or "Data Unavailable".

Output as valid JSON with these exact keys."""


def create_chat_report_node(llm: BaseChatModel):
    structured_llm = llm.with_structured_output(ChatReportResult)

    async def generate_report(state: dict) -> dict:
        analysis = state.get("summary", "")
        msg = HumanMessage(content=f"Analysis to summarize:\n\n{analysis}")
        result: ChatReportResult = await structured_llm.ainvoke(
            [SystemMessage(content=REPORT_PROMPT), msg]
        )
        return {
            "messages": [AIMessage(content=result.summary)],
            **result.model_dump(),
        }
    return generate_report
