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
    # Bot general chat now routes through Gemini (3.5 flash-lite) + Llama-70b fallback.
    assert settings.MODEL_HEAVY_REASONING in fast.model


def test_factory_uses_correct_model_strings(settings: Settings) -> None:
    factory = LLMFactory(settings)

    heavy = factory.get_heavy_reasoning_llm()
    structured = factory.get_structured_data_llm()
    fast = factory.get_fast_chat_llm()

    assert "gemini" in heavy.model.lower()
    assert structured.model == "openai/gpt-oss-120b"
    assert "gemini" in fast.model.lower()


def test_factory_ask_llm_uses_gpt_oss(settings: Settings) -> None:
    settings = Settings(
        BOT_TOKEN="test-token",
        GROQ_API_KEY="test-groq-key",
        GEMINI_API_KEY="test-gemini-key",
        OPENAI_API_KEY="test-openai-key",
    )
    factory = LLMFactory(settings)
    ask = factory.get_ask_llm()
    assert "gpt-oss" in ask.model.lower()


@patch("whaledecode.adapters.llm_graph.reasoner.build_investigation_graph")
@patch("whaledecode.adapters.llm_graph.reasoner.build_chat_investigation_graph")
def test_reasoner_uses_factory_llms(mock_chat_build, mock_invest_build, settings: Settings) -> None:
    mock_factory = MagicMock(spec=LLMFactory)
    heavy_llm = MagicMock(spec=BaseChatModel)
    fast_llm = MagicMock(spec=BaseChatModel)
    mock_factory.get_heavy_reasoning_llm.return_value = heavy_llm
    mock_factory.get_fast_chat_llm.return_value = fast_llm
    mock_factory.get_ask_llm.return_value = MagicMock(spec=BaseChatModel)

    reasoner = LangGraphReasoner(settings, mock_factory)

    assert mock_invest_build.call_count == 1
    assert mock_chat_build.call_count == 1
    assert mock_invest_build.call_args.args[0] is heavy_llm
    assert mock_chat_build.call_args.args[0] is fast_llm
    assert mock_invest_build.call_args.args[1] is reasoner._chain_provider
    assert mock_chat_build.call_args.args[1] is reasoner._chain_provider
    assert reasoner._heavy_llm is heavy_llm
    assert reasoner._fast_llm is fast_llm
