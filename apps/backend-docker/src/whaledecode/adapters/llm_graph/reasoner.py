import asyncio
import json
import time
from typing import Any

import structlog
from langchain_core.messages import HumanMessage
from whaledecode.adapters.chain.factory import create_chain_provider
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
        self._ask_llm = factory.get_ask_llm()
        self._chain_provider = create_chain_provider(settings)
        self._investigation_graph = build_investigation_graph(self._heavy_llm, self._chain_provider)
        self._chat_graph = build_chat_investigation_graph(self._fast_llm, self._chain_provider)
        self._memory_cms: dict[int, Any] = {}
        self._memory_graphs: dict[int, Any] = {}

    async def _invoke_graph(self, graph, inputs: dict[str, Any], label: str, config: dict | None = None) -> dict:
        """Invoke a LangGraph graph with one retry on transient errors."""
        for attempt in range(2):
            try:
                return await graph.ainvoke(inputs, config=config)
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
                "messages": [HumanMessage(content=json.dumps(event_input,default=str))],
            },
            "investigate_event",
        )
        tokens_in = self._count_tokens(state.get("messages", []))
        return {
            "summary": state.get("summary", ""),
            "fundamental_summary": state.get("fundamental_summary", ""),
            "technical_summary": state.get("technical_summary", ""),
            "bias_summary": state.get("bias_summary", ""),
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

    async def investigate_chat(self, chat_input: dict[str, Any], model: str = "chat") -> dict[str, Any]:
        start = time.monotonic()
        query = chat_input.get("message", "")
        inputs = {
            "query": query,
            "messages": [HumanMessage(content=f"User question: {query}")],
        }
        llm = self._ask_llm if model == "ask" else self._fast_llm
        thread_id = chat_input.get("thread_id")
        if thread_id and self._settings.DATABASE_URL:
            state = await self._invoke_chat_with_memory(inputs, thread_id, llm)
        else:
            graph = (
                self._chat_graph
                if llm is self._fast_llm
                else build_chat_investigation_graph(llm, self._chain_provider)
            )
            state = await self._invoke_graph(graph, inputs, "investigate_chat")
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

    async def _invoke_chat_with_memory(self, inputs: dict[str, Any], thread_id: str, llm) -> dict:
        """Run the chat graph with a Postgres checkpointer for per-user multi-turn memory.

        Each user's Telegram id becomes a LangGraph thread_id, so the graph state
        (the conversation) is persisted between /ask calls. The checkpointer
        connection is opened once per LLM and reused across calls; on any DB failure
        it is torn down and the stateless graph is used instead — memory degrades, the
        bot never dies, and no pool is opened per request.
        """
        try:
            return await self._invoke_graph(
                await self._get_memory_graph(llm),
                inputs,
                "investigate_chat",
                config={"configurable": {"thread_id": thread_id}},
            )
        except Exception as exc:
            log.warning("chat_memory_unavailable", thread_id=thread_id, error=str(exc)[:120])
            await self._reset_memory(llm)
            graph = (
                self._chat_graph
                if llm is self._fast_llm
                else build_chat_investigation_graph(llm, self._chain_provider)
            )
            return await self._invoke_graph(graph, inputs, "investigate_chat")

    async def _get_memory_graph(self, llm):
        """Return the chat graph for ``llm`` wired to a shared checkpointer, opening it on first use.

        ``from_conn_string`` is an async context manager, so the saver is entered
        here and kept alive (not exited) until ``close`` or a failure resets it.
        """
        key = id(llm)
        if key in self._memory_graphs:
            return self._memory_graphs[key]
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        cm = AsyncPostgresSaver.from_conn_string(self._settings.DATABASE_URL)
        saver = await cm.__aenter__()
        try:
            await saver.setup()
        except BaseException:
            await cm.__aexit__(None, None, None)
            raise
        self._memory_cms[key] = cm
        self._memory_graphs[key] = build_chat_investigation_graph(llm, self._chain_provider, checkpointer=saver)
        return self._memory_graphs[key]

    async def _reset_memory(self, llm=None) -> None:
        """Drop the shared checkpointer(s) so the next call retries with a fresh connection."""
        if llm is not None:
            key = id(llm)
            cm = self._memory_cms.pop(key, None)
            self._memory_graphs.pop(key, None)
            if cm is not None:
                await cm.__aexit__(None, None, None)
            return
        for cm in self._memory_cms.values():
            await cm.__aexit__(None, None, None)
        self._memory_cms.clear()
        self._memory_graphs.clear()

    async def close(self) -> None:
        """Release the shared chat-memory checkpointer connection(s)."""
        await self._reset_memory()

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
