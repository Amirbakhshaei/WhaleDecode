from unittest.mock import MagicMock, patch

import pytest
from langchain_core.language_models import BaseChatModel

from whaledecode.adapters.llm.factory import LLMFactory
from whaledecode.adapters.llm_graph.reasoner import LangGraphReasoner
from whaledecode.config.settings import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        BOT_TOKEN="test-token",
        GROQ_API_KEY="test-groq-key",
        GEMINI_API_KEY="test-gemini-key",
    )


def test_factory_returns_correct_model_types(settings: Settings) -> None:
    factory = LLMFactory(settings)

    heavy = factory.get_heavy_reasoning_llm()
    structured = factory.get_structured_data_llm()
    fast = factory.get_fast_chat_llm()

    assert isinstance(heavy, BaseChatModel)
    assert isinstance(structured, BaseChatModel)
    assert isinstance(fast, BaseChatModel)
    assert settings.MODEL_HEAVY_REASONING in heavy.model
    assert structured.model == settings.MODEL_STRUCTURED_DATA
    assert fast.model == settings.MODEL_FAST_CHAT


def test_factory_uses_correct_model_strings(settings: Settings) -> None:
    factory = LLMFactory(settings)

    heavy = factory.get_heavy_reasoning_llm()
    structured = factory.get_structured_data_llm()
    fast = factory.get_fast_chat_llm()

    assert "gemini-2.5-flash" in heavy.model
    assert structured.model == "llama-3.3-70b-versatile"
    assert fast.model == "llama-3.1-8b-instant"


@patch("whaledecode.adapters.llm_graph.reasoner.build_investigation_graph")
@patch("whaledecode.adapters.llm_graph.reasoner.build_chat_investigation_graph")
def test_reasoner_uses_factory_llms(mock_chat_build, mock_invest_build, settings: Settings) -> None:
    mock_factory = MagicMock(spec=LLMFactory)
    heavy_llm = MagicMock(spec=BaseChatModel)
    fast_llm = MagicMock(spec=BaseChatModel)
    mock_factory.get_heavy_reasoning_llm.return_value = heavy_llm
    mock_factory.get_fast_chat_llm.return_value = fast_llm

    reasoner = LangGraphReasoner(settings, mock_factory)

    mock_invest_build.assert_called_once_with(heavy_llm)
    mock_chat_build.assert_called_once_with(fast_llm)
    assert reasoner._heavy_llm is heavy_llm
    assert reasoner._fast_llm is fast_llm
