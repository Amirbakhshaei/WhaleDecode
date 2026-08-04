
import pytest
from whaledecode.adapters.telegram.middleware.throttling import ThrottlingMiddleware


class StubUser:
    id = 42


class StubFrom:
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
async def test_allows_one_then_drops_on_burst() -> None:
    event = StubEvent()
    middleware = ThrottlingMiddleware(max_rate=1, period_seconds=60, acquire_timeout=0.05)
    handled = 0

    async def counting_handler(*args, **kwargs):
        nonlocal handled
        handled += 1
        return "handled"

    assert await middleware(counting_handler, event, {}) == "handled"
    assert handled == 1

    result = await middleware(counting_handler, event, {})
    assert result is None
    assert handled == 1


@pytest.mark.asyncio
async def test_distinct_users_have_independent_limiters() -> None:
    middleware = ThrottlingMiddleware(max_rate=1, period_seconds=60, acquire_timeout=0.05)
    a = StubEvent(1)
    b = StubEvent(2)
    await _invoke(middleware, a)
    await _invoke(middleware, b)
    await _invoke(middleware, b)  # b's second call drops

    assert len(a.answers) == 0  # no drop message because stub isn't a real Message

    handled = 0

    async def counting_handler(*args, **kwargs):
        nonlocal handled
        handled += 1
        return "ok"

    assert await middleware(counting_handler, StubEvent(3), {}) == "ok"


@pytest.mark.asyncio
async def test_no_user_event_passes_through() -> None:
    middleware = ThrottlingMiddleware()
    event = object()

    async def handler(*args, **kwargs):
        return "passthrough"

    assert await middleware(handler, event, {}) == "passthrough"
