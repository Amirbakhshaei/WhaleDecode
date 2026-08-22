"""Ephemeral burst limiter for interactive Telegram users.

Each user gets a token-bucket ``AsyncLimiter`` (default 10 requests / 60 s).
When the burst limit forces the handler to wait longer than ``acquire_timeout``,
the request is dropped and the user is told to cool down.
"""
import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
from aiolimiter import AsyncLimiter

COOLING_DOWN_MSG = "🫧 System cooling down, please wait a moment."


class BurstRateLimitError(Exception):
    """Raised when a user exceeds the burst rate limit."""


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(
        self,
        max_rate: float = 10,
        period_seconds: float = 60,
        acquire_timeout: float = 1.0,
    ) -> None:
        self._max_rate = max_rate
        self._period = period_seconds
        self._timeout = acquire_timeout
        self._limiters: dict[int, AsyncLimiter] = {}

    def _limiter_for(self, user_id: int) -> AsyncLimiter:
        limiter = self._limiters.get(user_id)
        if limiter is None:
            limiter = AsyncLimiter(self._max_rate, self._period)
            self._limiters[user_id] = limiter
        return limiter

    @asynccontextmanager
    async def _burst(self, user_id: int):
        limiter = self._limiter_for(user_id)
        try:
            await asyncio.wait_for(limiter.acquire(), timeout=self._timeout)
        except (TimeoutError, asyncio.CancelledError) as exc:
            raise BurstRateLimitError from exc
        yield

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable[Any]],
        event: TelegramObject,
        data: dict,
    ) -> Any:
        user_id = getattr(getattr(event, "from_user", None), "id", None)
        if user_id is None:
            return await handler(event, data)
        try:
            async with self._burst(user_id):
                return await handler(event, data)
        except BurstRateLimitError:
            if isinstance(event, Message):
                await event.answer(COOLING_DOWN_MSG)
            return None
