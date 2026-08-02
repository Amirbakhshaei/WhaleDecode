"""Multi-provider LLM router using LangChain's native fallback mechanism."""

from collections.abc import AsyncIterator, Callable
from typing import Any

import structlog
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult
from langchain_core.runnables import Runnable, RunnableConfig
from pydantic import ConfigDict

log = structlog.get_logger()

_RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    OSError,
)

_RATE_LIMIT_INDICATORS = ("rate limit", "429", "503", "usage limit", "quota", "capacity")


def _is_retryable_error(exc: Exception) -> bool:
    """Check if an exception indicates a retryable rate-limit / capacity error."""
    if isinstance(exc, _RETRYABLE_EXCEPTIONS):
        return True
    err_str = str(exc).lower()
    return any(indicator in err_str for indicator in _RATE_LIMIT_INDICATORS)


class FallbackLLMRouter(BaseChatModel):
    """
    Wraps a primary LLM with one or more fallbacks using LangChain's native
    `with_fallbacks` mechanism.

    Automatically handles rate-limit errors (429, 503, quota) by cascading
    to the next available model.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    primary: BaseChatModel
    fallbacks: list[BaseChatModel] = []

    _should_fallback: Callable[[Exception], bool]
    _runnable: Runnable

    def __init__(
        self,
        primary: BaseChatModel,
        fallbacks: list[BaseChatModel] | None = None,
        *,
        should_fallback: Callable[[Exception], bool] | None = None,
        **kwargs: Any,
    ) -> None:
        # Pass fields to Pydantic's __init__ for proper validation
        super().__init__(
            primary=primary,
            fallbacks=fallbacks or [],
            **kwargs,
        )
        object.__setattr__(self, "_should_fallback", should_fallback or _is_retryable_error)
        object.__setattr__(self, "_runnable", self._build_runnable())

    def _build_runnable(self) -> Runnable:
        """Build the runnable chain with fallbacks."""
        runnable: Runnable = self.primary
        for fallback in self.fallbacks:
            runnable = runnable.with_fallbacks(
                [fallback],
                exception_key="error",
            )
        return runnable

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Sync generate with fallback support."""
        for attempt in range(len(self.fallbacks) + 1):
            try:
                return self.primary._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
            except Exception as exc:
                if attempt >= len(self.fallbacks):
                    raise
                if not self._should_fallback(exc):
                    raise
                log.warning(
                    "llm_fallback_sync",
                    attempt=attempt + 1,
                    error=str(exc)[:120],
                    fallback_model=self.fallbacks[attempt].__class__.__name__,
                )
                old_primary = self.primary
                object.__setattr__(self, "primary", self.fallbacks[attempt])
                object.__setattr__(self, "_runnable", self._build_runnable())
                try:
                    return self.primary._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
                finally:
                    object.__setattr__(self, "primary", old_primary)
                    object.__setattr__(self, "_runnable", self._build_runnable())
        raise RuntimeError("FallbackLLMRouter exhausted all models")

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Async generate with fallback support."""
        for attempt in range(len(self.fallbacks) + 1):
            try:
                return await self.primary._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
            except Exception as exc:
                if attempt >= len(self.fallbacks):
                    raise
                if not self._should_fallback(exc):
                    raise
                log.warning(
                    "llm_fallback_async",
                    attempt=attempt + 1,
                    error=str(exc)[:120],
                    fallback_model=self.fallbacks[attempt].__class__.__name__,
                )
                old_primary = self.primary
                object.__setattr__(self, "primary", self.fallbacks[attempt])
                object.__setattr__(self, "_runnable", self._build_runnable())
                try:
                    return await self.primary._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
                finally:
                    object.__setattr__(self, "primary", old_primary)
                    object.__setattr__(self, "_runnable", self._build_runnable())
        raise RuntimeError("FallbackLLMRouter exhausted all models")

    async def ainvoke(self, input: Any, config: RunnableConfig | None = None, **kwargs: Any) -> Any:
        return await self._runnable.ainvoke(input, config=config, **kwargs)

    def invoke(self, input: Any, config: RunnableConfig | None = None, **kwargs: Any) -> Any:
        return self._runnable.invoke(input, config=config, **kwargs)

    async def abatch(self, inputs: list[Any], config: RunnableConfig | None = None, **kwargs: Any) -> list[Any]:
        return await self._runnable.abatch(inputs, config=config, **kwargs)

    async def astream(self, input: Any, config: RunnableConfig | None = None, **kwargs: Any) -> AsyncIterator[Any]:
        async for chunk in self._runnable.astream(input, config=config, **kwargs):
            yield chunk

    def bind_tools(self, tools: list, **kwargs: Any) -> "FallbackLLMRouter":
        """Bind tools to all models in the chain."""
        primary_with_tools = self.primary.bind_tools(tools, **kwargs)
        fallbacks_with_tools = [fb.bind_tools(tools, **kwargs) for fb in self.fallbacks]
        return FallbackLLMRouter(primary_with_tools, fallbacks_with_tools, should_fallback=self._should_fallback)

    def with_config(self, config: RunnableConfig | None = None, **kwargs: Any) -> "FallbackLLMRouter":
        return FallbackLLMRouter(
            self.primary.with_config(config, **kwargs),
            [fb.with_config(config, **kwargs) for fb in self.fallbacks],
            should_fallback=self._should_fallback,
        )

    @property
    def _llm_type(self) -> str:
        return "fallback_router"

    @property
    def model_name(self) -> str:
        return getattr(self.primary, "model_name", self.primary.__class__.__name__)

    def __getattr__(self, name: str) -> Any:
        """Delegate unknown attributes to primary model."""
        return getattr(self.primary, name)


def create_groq_with_key_fallback(
    primary_key: str,
    model: str,
    secondary_key: str | None = None,
    **kwargs: Any,
) -> BaseChatModel:
    """Create a Groq LLM with optional secondary API key fallback."""
    from langchain_groq import ChatGroq

    primary = ChatGroq(
        model=model,
        groq_api_key=primary_key,
        **kwargs,
    )
    if secondary_key:
        fallback = ChatGroq(
            model=model,
            groq_api_key=secondary_key,
            **kwargs,
        )
        return FallbackLLMRouter(primary, [fallback])
    return primary


def create_gemini_with_groq_fallback(
    gemini_key: str,
    gemini_model: str,
    groq_key: str,
    groq_model: str,
    **kwargs: Any,
) -> BaseChatModel:
    """Create a Gemini primary with Groq fallback for heavy reasoning."""
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_groq import ChatGroq

    primary = ChatGoogleGenerativeAI(
        model=gemini_model,
        google_api_key=gemini_key,
        **kwargs,
    )
    fallback = ChatGroq(
        model=groq_model,
        groq_api_key=groq_key,
        **kwargs,
    )
    return FallbackLLMRouter(primary, [fallback])
