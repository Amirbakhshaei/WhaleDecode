"""Round-robin ChatOpenAI that rotates API keys on rate-limit errors."""

from typing import Any

from langchain_openai import ChatOpenAI

import structlog

log = structlog.get_logger()

_RATE_LIMIT_CODES = {429, 503}


class RotatingChatOpenAI(ChatOpenAI):
    """Primary ChatOpenAI with a list of fallback API keys.

    On rate-limit / usage-limit errors, swaps to the next key and retries once.
    """

    _secondary_keys: list[str]
    _key_idx: int = 0

    def __init__(self, *, secondary_keys: list[str] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        object.__setattr__(self, "_secondary_keys", secondary_keys or [])
        object.__setattr__(self, "_key_idx", 0)

    def _next_key(self) -> str | None:
        if not self._secondary_keys:
            return None
        key = self._secondary_keys[self._key_idx % len(self._secondary_keys)]
        self._key_idx += 1
        return key

    async def _agenerate(self, messages, *, run_manager=None, **kwargs: Any):
        try:
            return await super()._agenerate(messages, run_manager=run_manager, **kwargs)
        except Exception as exc:
            status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
            is_rate_limit = status in _RATE_LIMIT_CODES or "rate" in str(exc).lower()
            if not is_rate_limit:
                raise

            next_key = self._next_key()
            if not next_key:
                raise

            log.warning("llm_key_rotated", error=str(exc)[:120])
            old_key = self.openai_api_key
            object.__setattr__(self, "openai_api_key", next_key)
            try:
                return await super()._agenerate(messages, run_manager=run_manager, **kwargs)
            finally:
                object.__setattr__(self, "openai_api_key", old_key)
