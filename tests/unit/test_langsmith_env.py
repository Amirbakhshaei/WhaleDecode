import os

from langsmith.utils import get_env_var, tracing_is_enabled
from whaledecode.config.settings import Settings


def _clean_env() -> None:
    get_env_var.cache_clear()
    for k in list(os.environ):
        if k.startswith("LANGCHAIN_") or k.startswith("LANGSMITH_"):
            os.environ.pop(k)


def _settings() -> Settings:
    return Settings(BOT_TOKEN="test", GROQ_API_KEY="test", _env_file=None)


class TestInjectLangsmithEnv:
    def test_injects_lowercase_true(self) -> None:
        _clean_env()
        _settings().inject_langsmith_env()
        assert os.environ["LANGSMITH_TRACING"] == "true"
        assert tracing_is_enabled() is True

    def test_tracing_disabled_when_false(self) -> None:
        _clean_env()
        settings = _settings()
        settings.LANGSMITH_TRACING = False
        settings.inject_langsmith_env()
        assert os.environ["LANGSMITH_TRACING"] == "false"
        assert tracing_is_enabled() is False

    def test_injects_key_and_project(self) -> None:
        _clean_env()
        settings = _settings()
        settings.LANGSMITH_API_KEY = "ls_test_key"
        settings.LANGSMITH_PROJECT = "WhaleDecode"
        settings.inject_langsmith_env()
        assert os.environ["LANGSMITH_API_KEY"] == "ls_test_key"
        assert os.environ["LANGSMITH_PROJECT"] == "WhaleDecode"
