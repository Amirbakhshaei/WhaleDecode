import asyncio
import json
import time
from typing import Any

import structlog
from langchain_core.messages import HumanMessage

from whaledecode.adapters.llm.factory import LLMFactory
from whaledecode.adapters.llm_graph.graphs.chat_investigation import build_chat_investigation_graph
from whaledecode.adapters.llm_graph.graphs.investigation_graph import build_investigation_graph
from whaledecode.config.settings import Settings
from whaledecode.domain.ports.reasoner import ReasonerPort

log = structlog.get_logger()


class LangGraphReasoner(ReasonerPort):
    def __init__(self, settings: Settings, factory: LLMFactory) -> None:
        self._settings = settings
        self._heavy_llm = factory.get_heavy_reasoning_llm()
        self._fast_llm = factory.get_fast_chat_llm()
        self._investigation_graph = build_investigation_graph(self._heavy_llm)
        self._chat_graph = build_chat_investigation_graph(self._fast_llm)

    async def _invoke_graph(self, graph, inputs: dict[str, Any], label: str) -> dict:
        """Invoke a LangGraph graph with one retry on transient errors."""
        for attempt in range(2):
            try:
                return await graph.ainvoke(inputs)
            except (ConnectionError, TimeoutError, OSError) as exc:
                if attempt == 0:
                    log.warning("llm_retry", attempt=1, label=label, error=str(exc)[:120])
                    await asyncio.sleep(1)
                else:
                    raise

    async def investigate_event(self, event_input: dict[str, Any]) -> dict[str, Any]:
        start = time.monotonic()
        # The event enters the graph as the opening user turn — the analysis node must
        # not re-inject it, or Gemini rejects the message sequence.
        state = await self._invoke_graph(
            self._investigation_graph,
            {
                "event_data": event_input,
                "messages": [HumanMessage(content=json.dumps(event_input,`default=str`))],
            },
            "investigate_event",
        )
        tokens_in = self._count_tokens(state.get("messages", []))
        return {
            "summary": state.get("summary", ""),
            "risk_score": state.get("risk_score", 0.0),
            "is_safe": state.get("is_safe", True),
            "thesis": state.get("thesis", ""),
            "evidence": state.get("evidence", []),
            "tool_calls": state.get("tool_calls", []),
            "disclaimer": state.get("disclaimer", ""),
            "latency_ms": int((time.monotonic() - start) * 1000),
            "tokens_in": tokens_in,
            "tokens_out": self._count_tokens(state.get("messages", [])),
        }

    async def investigate_chat(self, chat_input: dict[str, Any]) -> dict[str, Any]:
        start = time.monotonic()
        query = chat_input.get("message", "")
        state = await self._invoke_graph(
            self._chat_graph,
            {
                "query": query,
                "messages": [HumanMessage(content=f"User question: {query}")],
            },
            "investigate_chat",
        )
        tokens_in = self._count_tokens(state.get("messages", []))
        return {
            "summary": state.get("summary", ""),
            "risk_score": state.get("risk_score", 0.0),
            "is_safe": state.get("is_safe", True),
            "thesis": state.get("thesis", ""),
            "evidence": state.get("evidence", []),
            "tool_calls": state.get("tool_calls", []),
            "disclaimer": state.get("disclaimer", ""),
            "latency_ms": int((time.monotonic() - start) * 1000),
            "tokens_in": tokens_in,
            "tokens_out": self._count_tokens(state.get("messages", [])),
        }

    async def generate_briefing(self, briefing_input: dict[str, Any]) -> dict[str, Any]:
        start = time.monotonic()
        events = briefing_input.get("events", [])
        if not events:
            return {"summary": "No notable events today.", "events": [], "latency_ms": 0}

        lines = []
        for e in events[:20]:
            score = e.get("score", 0)
            bar = "🟢" if score < 0.4 else "🟡" if score < 0.7 else "🔴"
            addr = e.get("address", "")[:8]
            chain = e.get("chain", "")
            event_type = e.get("event_type", "UNKNOWN")
            label = e.get("label", "")
            lines.append(f"- {bar} {label} ({addr}…) on {chain} — {event_type} (score {score:.1f})")

        prompt = (
            "You are a crypto briefing analyst. Summarize the day's whale activity "
            "in 2-3 paragraphs. Highlight the most significant events, patterns, and risks.\n\n"
            f"Events today ({len(events)} total):\n" + "\n".join(lines)
        )
        messages = [{"role": "user", "content": prompt}]
        for attempt in range(2):
            try:
                resp = await self._heavy_llm.ainvoke(messages)
                break
            except (ConnectionError, TimeoutError, OSError) as exc:
                if attempt == 0:
                    log.warning("llm_retry", attempt=1, label="generate_briefing", error=str(exc)[:120])
                    await asyncio.sleep(1)
                else:
                    raise

        lat_ms = int((time.monotonic() - start) * 1000)
        return {
            "summary": resp.content,
            "events": events[:10],
            "latency_ms": lat_ms,
        }

    def _count_tokens(self, messages: list) -> int:
        total = 0
        for msg in messages:
            if hasattr(msg, "usage_metadata") and msg.usage_metadata:
                total += (msg.usage_metadata.get("input_tokens", 0) or 0)
                total += (msg.usage_metadata.get("output_tokens", 0) or 0)
            elif hasattr(msg, "response_metadata") and msg.response_metadata:
                usage = msg.response_metadata.get("token_usage", {}) or {}
                total += usage.get("prompt_tokens", 0) or 0
                total += usage.get("completion_tokens", 0) or 0
        return total
