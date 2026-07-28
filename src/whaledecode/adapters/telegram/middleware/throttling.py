import time
from collections.abc import Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, rate_limit: float = 0.5) -> None:
        self._rate_limit = rate_limit
        self._last_time: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable],
        event: TelegramObject,
        data: dict,
    ) -> None:
        user_id = getattr(getattr(event, "from_user", None), "id", None)
        if user_id is not None:
            now = time.monotonic()
            last = self._last_time.get(user_id, 0)
            if now - last < self._rate_limit:
                return
            self._last_time[user_id] = now
        return await handler(event, data)
