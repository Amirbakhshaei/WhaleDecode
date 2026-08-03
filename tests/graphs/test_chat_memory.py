from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.language_models import BaseChatModel
from whaledecode.adapters.llm.factory import LLMFactory
from whaledecode.adapters.llm_graph.reasoner import LangGraphReasoner
from whaledecode.config.settings import Settings


def _settings(database_url: str = "") -> Settings:
    return Settings(
        BOT_TOKEN="test-token",
        GROQ_API_KEY="test-groq-key",
        GEMINI_API_KEY="test-gemini-key",
        DATABASE_URL=database_url,
    )


def _state() -> dict:
    return {
        "summary": "ok",
        "risk_score": 0.5,
        "is_safe": True,
        "thesis": "t",
        "evidence": [],
        "tool_calls": [],
        "disclaimer": "d",
        "messages": [],
    }


def _make_reasoner(settings: Settings):
    factory = MagicMock(spec=LLMFactory)
    factory.get_heavy_reasoning_llm.return_value = MagicMock(spec=BaseChatModel)
    factory.get_fast_chat_llm.return_value = MagicMock(spec=BaseChatModel)
    return LangGraphReasoner(settings, factory)


@patch("whaledecode.adapters.llm_graph.reasoner.build_chat_investigation_graph")
@pytest.mark.asyncio
async def test_memory_path_invokes_graph_with_thread_config(mock_build) -> None:
    mock_graph = AsyncMock()
    mock_graph.ainvoke.return_value = _state()
    mock_build.return_value = mock_graph

    saver = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__.return_value = saver
    reasoner = _make_reasoner(_settings("postgresql://u:p@h:5432/db"))

    with patch(
        "langgraph.checkpoint.postgres.aio.AsyncPostgresSaver.from_conn_string",
        new=MagicMock(return_value=cm),
    ):
        result = await reasoner.investigate_chat({"message": "hi", "thread_id": "42"})

    assert result["summary"] == "ok"
    assert mock_build.call_args.kwargs["checkpointer"] is saver
    assert mock_graph.ainvoke.call_args.kwargs["config"] == {"configurable": {"thread_id": "42"}}


@patch("whaledecode.adapters.llm_graph.reasoner.build_chat_investigation_graph")
@pytest.mark.asyncio
async def test_memory_path_falls_back_to_stateless_graph_on_db_error(mock_build) -> None:
    stateless = AsyncMock()
    stateless.ainvoke.return_value = _state()
    mock_build.side_effect = [stateless, RuntimeError("boom")]

    reasoner = _make_reasoner(_settings("postgresql://u:p@h:5432/db"))

    with patch(
        "langgraph.checkpoint.postgres.aio.AsyncPostgresSaver.from_conn_string",
        new=MagicMock(side_effect=ConnectionError("db down")),
    ):
        result = await reasoner.investigate_chat({"message": "hi", "thread_id": "42"})

    assert result["summary"] == "ok"
    assert stateless.ainvoke.call_count == 1
    assert stateless.ainvoke.call_args.kwargs.get("config") is None


@patch("whaledecode.adapters.llm_graph.reasoner.build_chat_investigation_graph")
@pytest.mark.asyncio
async def test_no_thread_id_uses_stateless_graph(mock_build) -> None:
    stateless = AsyncMock()
    stateless.ainvoke.return_value = _state()
    mock_build.return_value = stateless

    reasoner = _make_reasoner(_settings("postgresql://u:p@h:5432/db"))

    with patch(
        "langgraph.checkpoint.postgres.aio.AsyncPostgresSaver.from_conn_string"
    ) as from_conn:
        result = await reasoner.investigate_chat({"message": "hi"})

    assert result["summary"] == "ok"
    from_conn.assert_not_called()
    assert stateless.ainvoke.call_count == 1
