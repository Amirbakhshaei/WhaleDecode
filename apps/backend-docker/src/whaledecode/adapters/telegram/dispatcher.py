import asyncio
import time
from typing import Any

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from whaledecode.domain.ports.alert_dispatcher import AlertDispatcherPort

log = structlog.get_logger()


async def safe_telegram_send(bot: Bot, chat_id: int | str, text: str, **kwargs: Any):
    """Send with flood-control backoff.

    On a 429 (``TelegramRetryAfter``) sleeps the server-mandated window; other
    Telegram API errors get exponential backoff (4 attempts total).
    """
    for attempt in range(4):
        try:
            return await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except TelegramRetryAfter as e:
            log.warning("telegram_flood_control", chat_id=chat_id, retry_after=e.retry_after)
            await asyncio.sleep(e.retry_after + 1)
        except TelegramAPIError as e:
            log.error("telegram_dispatch_failed", chat_id=chat_id, error=str(e))
            if attempt == 3:
                raise
            await asyncio.sleep(2**attempt)
    return None


class TokenBucketRateLimiter:
    """Bounded token bucket: refills ``rate`` tokens/second up to ``capacity``.

    ``acquire`` blocks until a token is available, so callers self-throttle to
    ``rate`` sends per second without ever exceeding the Telegram API ceiling.
    """

    def __init__(self, rate: float = 20.0, capacity: float = 20.0) -> None:
        self._rate = rate
        self._capacity = capacity
        self._tokens = capacity
        self._last = time.monotonic()

    async def acquire(self) -> None:
        while True:
            now = time.monotonic()
            self._tokens = min(self._capacity, self._tokens + (now - self._last) * self._rate)
            self._last = now
            if self._tokens >= 1:
                self._tokens -= 1
                return
            await asyncio.sleep((1 - self._tokens) / self._rate)


class RateLimitedDispatcher(AlertDispatcherPort):
    """Wraps a dispatcher, gating every send through a token-bucket limiter."""

    def __init__(
        self,
        inner: AlertDispatcherPort,
        limiter: TokenBucketRateLimiter | None = None,
    ) -> None:
        self._inner = inner
        self._limiter = limiter or TokenBucketRateLimiter()

    def set_bot(self, bot: Bot) -> None:
        self._inner.set_bot(bot)

    async def dispatch(self, user_id: int, message: str, buttons: list[list[dict]] | None = None) -> bool:
        await self._limiter.acquire()
        return await self._inner.dispatch(user_id, message, buttons)

    async def dispatch_briefing(self, user_id: int, message: str) -> bool:
        await self._limiter.acquire()
        return await self._inner.dispatch_briefing(user_id, message)


class TelegramAlertDispatcher(AlertDispatcherPort):
    def __init__(self) -> None:
        self._log = structlog.get_logger()
        self._bot: Bot | None = None

    def set_bot(self, bot: Bot) -> None:
        self._bot = bot

    async def dispatch(self, user_id: int, message: str, buttons: list[list[dict]] | None = None) -> bool:
        bot = self._bot
        if bot is None:
            self._log.warning("dispatch_no_bot", user_id=user_id)
            return False
        try:
            await bot.send_message(chat_id=user_id, text=message, parse_mode=None)
            self._log.info("dispatch", user_id=user_id, preview=message[:50])
            return True
        except Exception as e:
            self._log.error("dispatch_error", user_id=user_id, error=str(e))
            return False

    dispatch_briefing = dispatch
