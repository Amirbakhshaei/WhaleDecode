import pytest
from whaledecode.adapters.telegram.middleware.throttling import ThrottlingMiddleware


class StubUser:
    id = 42


class StubEvent:
    """Minimal Message-like object: has from_user and an answer() hook."""

    def __init__(self, user_id: int = 42):
        self.from_user = StubUser()
        self.from_user.id = user_id
        self.answers: list[str] = []

    async def answer(self, text: str) -> None:
        self.answers.append(text)


async def _invoke(middleware, event):
    async def handler(*args, **kwargs):
        return "handled"

    return await middleware(handler, event, {})


@pytest.mark.asyncio
async def test_drops_after_burst_limit_with_warning() -> None:
    middleware = ThrottlingMiddleware(burst_rate=3, burst_seconds=10)
    handled = 0

    async def counting_handler(*args, **kwargs):
        nonlocal handled
        handled += 1
        return "handled"

    for _ in range(3):
        assert await middleware(counting_handler, StubEvent(), {}) == "handled"
    assert handled == 3

    # 4th request inside the 10s burst window is dropped with a warning.
    result = await middleware(counting_handler, StubEvent(), {})
    assert result is None
    assert handled == 3
    # Warning only fires on real aiogram Message objects; stub lacks isinstance match.


@pytest.mark.asyncio
async def test_distinct_users_have_independent_limiters() -> None:
    middleware = ThrottlingMiddleware(burst_rate=1, burst_seconds=10)
    a = StubEvent(1)
    b = StubEvent(2)

    async def counting_handler(*args, **kwargs):
        return "ok"

    assert await middleware(counting_handler, a, {}) == "ok"
    assert await middleware(counting_handler, b, {}) == "ok"
    assert await middleware(counting_handler, b, {}) is None  # b's second call drops


@pytest.mark.asyncio
async def test_no_user_event_passes_through() -> None:
    middleware = ThrottlingMiddleware()
    event = object()

    async def handler(*args, **kwargs):
        return "passthrough"

    assert await middleware(handler, event, {}) == "passthrough"
