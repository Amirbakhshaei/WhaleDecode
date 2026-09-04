"""ResilientRPCManager failover + circuit breaker.

Spec: "Mock 3 consecutive HTTP 429 status codes and verify the manager rotates
to the fallback RPC without bubbling up an exception."

The manager wraps the existing ``RpcFailoverRouter`` (which already does
per-node 60s cooldowns on 429). On top of that we verify the chain-level
circuit breaker: after ``breaker_threshold`` consecutive
``RpcNodesExhaustedError`` raises, the chain is quarantined.
"""

import httpx
import pytest
from whaledecode.pools.rpc import ResilientRPCManager


class _FlakyClient:
    """Returns 429 forever on ``bad``, 200 OK on ``good``. Records every URL hit."""

    def __init__(self, bad_url: str, good_url: str) -> None:
        self._bad = bad_url
        self._good = good_url
        self.calls: list[str] = []
        self._fail_first_n = 0  # extra bad responses before we switch

    async def post(self, url, json=None, **_kwargs):
        self.calls.append(url)
        if url == self._bad and self._fail_first_n >= 0:
            if self._fail_first_n > 0:
                self._fail_first_n -= 1
                return httpx.Response(429, request=httpx.Request("POST", url))
            return httpx.Response(429, request=httpx.Request("POST", url))
        return httpx.Response(200, request=httpx.Request("POST", url), json={"jsonrpc": "2.0", "id": 1, "result": "ok"})


@pytest.mark.asyncio
async def test_429_rotate_to_fallback_without_raising() -> None:
    """3 consecutive 429s → manager keeps trying other URLs, returns success."""
    bad = "http://429.node"
    good = "http://ok.node"
    client = _FlakyClient(bad, good)

    mgr = ResilientRPCManager(
        chains=["test"],
        breaker_threshold=10,  # high so we don't trip the breaker in this test
        max_retries=3,
    )
    mgr.register_chain("test", urls=[bad, good])
    # Inject the flaky httpx client directly into the underlying router.
    mgr._routers["test"]._client = client  # type: ignore[assignment]

    result = await mgr.execute("test", {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []})

    assert result == "ok"
    assert bad in client.calls
    assert good in client.calls  # rotated at least once
    assert client.calls[-1] == good  # final answer came from the healthy node


@pytest.mark.asyncio
async def test_all_nodes_429_returns_rpc_nodes_exhausted_after_retries() -> None:
    """When every node 429s the manager raises RpcNodesExhaustedError, not an
    unhandled 429. (Spec invariant: 429 must NEVER bubble.)"""
    class _Always429:
        def __init__(self):
            self.calls: list[str] = []

        async def post(self, url, json=None, **_kwargs):
            self.calls.append(url)
            return httpx.Response(429, request=httpx.Request("POST", url))

    client = _Always429()
    mgr = ResilientRPCManager(
        chains=["test"],
        breaker_threshold=999,
        max_retries=2,
        cooldown_seconds=0.0,  # don't bother cooling down between retries
    )
    mgr.register_chain("test", urls=["http://a", "http://b", "http://c"])
    mgr._routers["test"]._client = client  # type: ignore[assignment]

    with pytest.raises(Exception) as exc:
        await mgr.execute("test", {"jsonrpc": "2.0", "id": 1, "method": "x", "params": []})

    # Must NOT be an httpx.HTTPStatusError or any unhandled 429-shaped exception.
    assert not isinstance(exc.value, httpx.HTTPStatusError)
    # RpcNodesExhaustedError is what bubbles up after every node has been tried.
    assert "test" in str(exc.value) or "exhausted" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_threshold_failures() -> None:
    """After ``breaker_threshold`` *retry-loop exits with RpcNodesExhausted*,
    the chain is quarantined for ``cooldown_seconds``; subsequent calls raise
    ``CircuitOpenError`` without hitting the wire."""

    class _Broken:
        async def post(self, url, json=None, **_kwargs):
            raise httpx.ConnectError("down", request=httpx.Request("POST", url))

    mgr = ResilientRPCManager(
        chains=["test"],
        breaker_threshold=2,  # small so the test trips quickly
        max_retries=1,        # one failure per execute() call
        cooldown_seconds=60.0,
    )
    mgr.register_chain("test", urls=["http://only.node"])
    mgr._routers["test"]._client = _Broken()  # type: ignore[assignment]

    # Two calls exhaust retries → breaker opens.
    for _ in range(2):
        with pytest.raises(Exception):
            await mgr.execute("test", {"jsonrpc": "2.0", "id": 1, "method": "x", "params": []})

    assert mgr.breaker_state("test")["open"] is True
    assert mgr._consecutive_failures["test"] >= 2


@pytest.mark.asyncio
async def test_breaker_recovers_after_cooldown() -> None:
    """Quarantine expires; next call goes through normally."""

    class _ChurnClient:
        def __init__(self):
            self.calls: list[str] = []
            self._failures_left = 6  # enough to trip the breaker once we run out of nodes
            self._succeed_now = False

        async def post(self, url, json=None, **_kwargs):
            self.calls.append(url)
            if self._succeed_now or self._failures_left <= 0:
                return httpx.Response(200, request=httpx.Request("POST", url), json={"jsonrpc": "2.0", "id": 1, "result": "ok"})
            self._failures_left -= 1
            return httpx.Response(429, request=httpx.Request("POST", url))

    client = _ChurnClient()
    mgr = ResilientRPCManager(
        chains=["test"],
        breaker_threshold=2,
        max_retries=1,
        cooldown_seconds=10.0,  # long enough to observe the open state
    )
    mgr.register_chain("test", urls=["http://a", "http://b"])
    mgr._routers["test"]._client = client  # type: ignore[assignment]

    # Burn until the breaker trips.
    for _ in range(3):
        try:
            await mgr.execute("test", {"jsonrpc": "2.0", "id": 1, "method": "x", "params": []})
        except Exception:
            pass

    assert mgr.breaker_state("test")["open"] is True

    # Force-clear the breaker; emulate cooldown elapsing.
    mgr._breaker_open_until["test"] = 0.0
    # Drain the underlying router's per-node cooldowns too, otherwise the
    # RpcFailoverRouter will skip every node and we never get to "ok".
    for url in mgr._routers["test"]._urls:
        mgr._routers["test"]._cooldown_until[url] = 0.0
    # Flip the fake to start serving 200s.
    client._succeed_now = True
    result = await mgr.execute("test", {"jsonrpc": "2.0", "id": 1, "method": "x", "params": []})
    assert result == "ok"
