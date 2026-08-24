"""Two-tier ephemeral burst limiter for interactive Telegram users.

Per user: max 3 requests / 10 seconds AND max 15 requests / minute.
Either limit tripping drops the request with a cooldown warning.
"""
import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
from aiolimiter import AsyncLimiter

RATE_LIMIT_MSG = "⚠️ Rate limit exceeded. Please wait a moment before sending more queries."


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(
        self,
        burst_rate: int = 3,
        burst_seconds: float = 10,
        minute_rate: int = 15,
    ) -> None:
        self._burst = (burst_rate, burst_seconds)
        self._minute = minute_rate
        self._limiters: dict[int, tuple[AsyncLimiter, AsyncLimiter]] = {}

    def _limiters_for(self, user_id: int) -> tuple[AsyncLimiter, AsyncLimiter]:
        pair = self._limiters.get(user_id)
        if pair is None:
            pair = (
                AsyncLimiter(self._burst[0], self._burst[1]),
                AsyncLimiter(self._minute, 60),
            )
            self._limiters[user_id] = pair
        return pair

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable[Any]],
        event: TelegramObject,
        data: dict,
    ) -> Any:
        user_id = getattr(getattr(event, "from_user", None), "id", None)
        if user_id is None:
            return await handler(event, data)
        burst, minute = self._limiters_for(user_id)
        # has_capacity() probes without consuming a token, so a blocked request
        # is dropped without burning quota on either tier.
        if not (burst.has_capacity() and minute.has_capacity()):
            if isinstance(event, Message):
                await event.answer(RATE_LIMIT_MSG)
            return None
        await asyncio.gather(burst.acquire(), minute.acquire())
        return await handler(event, data)
