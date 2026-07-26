import time
from typing import Any

from langchain_openai import ChatOpenAI

from whaledecode.adapters.llm_graph.graphs.investigation_graph import build_investigation_graph
from whaledecode.config.models import DEFAULT_MODEL_CONFIG
from whaledecode.config.settings import Settings
from whaledecode.domain.ports.reasoner import ReasonerPort


class LangGraphReasoner(ReasonerPort):
    def __init__(self, settings: Settings) -> None:
        strong_llm = ChatOpenAI(
            model=DEFAULT_MODEL_CONFIG.strong_id,
            api_key=settings.GROQ_API_KEY.get_secret_value(),
            base_url=settings.GROQ_BASE_URL,
            temperature=0.2,
        )
        self._investigation_graph = build_investigation_graph(strong_llm)

    async def investigate_event(self, event_input: dict[str, Any]) -> dict[str, Any]:
        start = time.monotonic()
        state = await self._investigation_graph.ainvoke({"event_data": event_input})
        return {
            "summary": state.get("summary", ""),
            "risk_score": state.get("risk_score", 0.0),
            "thesis": state.get("thesis", ""),
            "evidence": state.get("evidence", []),
            "tool_calls": state.get("tool_calls", []),
            "disclaimer": state.get("disclaimer", ""),
            "latency_ms": int((time.monotonic() - start) * 1000),
        }

    async def investigate_chat(self, chat_input: dict[str, Any]) -> dict[str, Any]:
        return {"response": "Chat investigation is not yet implemented.", "latency_ms": 0}

    async def generate_briefing(self, briefing_input: dict[str, Any]) -> dict[str, Any]:
        return {"briefing": "Briefing generation is not yet implemented.", "latency_ms": 0}
