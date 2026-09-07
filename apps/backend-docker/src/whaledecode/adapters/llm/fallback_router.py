"""Multi-provider LLM router using LangChain's native fallback mechanism."""

import asyncio
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

# ponytail: Gemini free tier (250k input tokens/min) returns a structured
# ResourceExhausted with an embedded retryDelay. Catching the concrete type
# is sturdier than substring-matching the rendered message — Google SDK
# versions rotate the wording but keep the type stable.
try:
    from google.api_core.exceptions import ResourceExhausted as _GoogleResourceExhausted

    _QUOTA_EXCEPTIONS: tuple[type[BaseException], ...] = (_GoogleResourceExhausted,)
except ImportError:  # google-api-core not installed (Groq-only deploys)
    _GoogleResourceExhausted = None  # type: ignore[assignment]
    _QUOTA_EXCEPTIONS = ()

try:
    from grpc import StatusCode as _GrpcStatusCode
    from grpc.aio import AioRpcError as _AioRpcError

    def _is_aio_resource_exhausted(exc: BaseException) -> bool:
        code = getattr(exc, "code", lambda: None)()
        return _AioRpcError is not None and isinstance(exc, _AioRpcError) and code == _GrpcStatusCode.RESOURCE_EXHAUSTED

except ImportError:
    _AioRpcError = None  # type: ignore[assignment]

    def _is_aio_resource_exhausted(exc: BaseException) -> bool:
        return False


_QUOTA_DEFAULT_BACKOFF_SECONDS = 45.0
_QUOTA_MAX_RETRIES = 3


def _extract_retry_delay(exc: BaseException) -> float:
    """Read the upstream ``retry_delay`` seconds off a Google quota error.

    Returns ``_QUOTA_DEFAULT_BACKOFF_SECONDS`` when the SDK isn't installed or
    no delay is exposed — better than guessing a worse number.
    """
    if _GoogleResourceExhausted is not None and isinstance(exc, _GoogleResourceExhausted):
        try:
            delay = exc.retry_delay  # google.api_core.exceptions.RetryError typed
            if delay is not None:
                return max(float(delay.total_seconds()), 1.0)
        except AttributeError:
            pass
    metadata = getattr(exc, "metadata", None) or {}
    if isinstance(metadata, dict):
        retry_after = metadata.get("retry-after") or metadata.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), 1.0)
            except (TypeError, ValueError):
                pass
    return _QUOTA_DEFAULT_BACKOFF_SECONDS


def _is_quota_error(exc: BaseException) -> bool:
    """True when ``exc`` is a Gemini/Groq quota-exhausted (transient, retryable)."""
    if _QUOTA_EXCEPTIONS and isinstance(exc, _QUOTA_EXCEPTIONS):
        return True
    if _is_aio_resource_exhausted(exc):
        return True
    err_str = str(exc).lower()
    return any(indicator in err_str for indicator in _RATE_LIMIT_INDICATORS)


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

    primary: Runnable
    fallbacks: list[Runnable] = []

    _should_fallback: Callable[[Exception], bool]
    _runnable: Runnable

    def __init__(
        self,
        primary: Runnable,
        fallbacks: list[Runnable] | None = None,
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
            runnable = runnable.with_fallbacks([fallback], exceptions_to_handle=(Exception,))
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
        """Async generate with fallback support.

        Quota errors (Gemini ``ResourceExhausted`` / gRPC ``RESOURCE_EXHAUSTED``)
        are retried on the *primary* model after the upstream ``retry_delay``
        instead of cascading to the fallback — a 429 means the primary will be
        free again in seconds, while burning the fallback just hides the real
        problem and loses context. Other errors still cascade.
        """
        last_quota_exc: BaseException | None = None
        for attempt in range(_QUOTA_MAX_RETRIES):
            try:
                return await self.primary._agenerate(
                    messages, stop=stop, run_manager=run_manager, **kwargs
                )
            except Exception as exc:
                if not _is_quota_error(exc):
                    raise
                delay = _extract_retry_delay(exc)
                last_quota_exc = exc
                log.warning(
                    "llm_quota_throttled",
                    attempt=attempt + 1,
                    delay_seconds=round(delay, 2),
                    model=self.primary.__class__.__name__,
                    error=str(exc)[:160],
                )
                await asyncio.sleep(delay)
        # Retries exhausted on a quota error — surface it rather than silently
        # switching providers (the caller is best positioned to decide).
        if last_quota_exc is not None:
            raise last_quota_exc

        # Non-quota errors: cascade through fallbacks.
        for attempt in range(len(self.fallbacks)):
            try:
                return await self.fallbacks[attempt]._agenerate(
                    messages, stop=stop, run_manager=run_manager, **kwargs
                )
            except Exception as exc:
                if attempt >= len(self.fallbacks) - 1:
                    raise
                if not self._should_fallback(exc):
                    raise
                log.warning(
                    "llm_fallback_async",
                    attempt=attempt + 1,
                    error=str(exc)[:120],
                    fallback_model=self.fallbacks[attempt].__class__.__name__,
                )
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
        max_retries=0,
        timeout=15,
        **kwargs,
    )
    if secondary_key:
        fallback = ChatGroq(
            model=model,
            groq_api_key=secondary_key,
            max_retries=0,
            timeout=15,
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
        max_retries=0,
        timeout=15,
        **kwargs,
    )
    fallback = ChatGroq(
        model=groq_model,
        groq_api_key=groq_key,
        max_retries=0,
        timeout=15,
        **kwargs,
    )
    return FallbackLLMRouter(primary, [fallback])
