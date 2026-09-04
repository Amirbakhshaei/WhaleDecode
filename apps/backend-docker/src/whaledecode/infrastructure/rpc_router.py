"""RPC failover router: round-robin over free public nodes with cooldown penalties.

Sole owner of transport concerns (HTTP, status codes, timeouts). Callers see a
single ``post()`` that either returns a JSON-RPC result or raises — network
volatility never leaks into chain adapters.

Demonstrates the Circuit Breaker pattern per node: a failing endpoint is
flagged with a temporary cooldown and skipped, then automatically retried
after the penalty expires. No health-check thread needed — real traffic is
the probe.
"""
import itertools
import time
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

# Status codes meaning "this node is unhealthy/rate-limited for us" → failover.
# 520-524: Cloudflare-origin failures (llamarpc et al. return bare 521s).
_FAILOVER_STATUS = {429, 500, 502, 503, 504, 520, 521, 522, 523, 524}

# JSON-RPC error codes meaning "this node won't/can't serve this request"
# (capacity, tier restriction, method gating, internal server failure) rather
# than "our params are wrong" → treat the node as unavailable for now and
# rotate. -32603 is the JSON-RPC spec's "server-side internal error".
_NODE_CAPACITY_CODES = {-32046, -32701, -32005, -32603}
_CAPACITY_MESSAGE_HINTS = (
    "cannot fulfill",
    "rate limit",
    "too many requests",
    "specify an address",
    "dedicated full node",
    "exceeded",
)


def _is_node_capacity_error(err: dict) -> bool:
    if err.get("code") in _NODE_CAPACITY_CODES:
        return True
    message = str(err.get("message", "")).lower()
    return any(hint in message for hint in _CAPACITY_MESSAGE_HINTS)


def to_int(val: Any) -> int:
    """Safe conversion of JSON-RPC scalars (hex str, decimal str, or int).

    Also handles dict responses (error payloads or wrapped results) by extracting
    the 'result' field or raising ConnectionError for error payloads.
    """
    if isinstance(val, bool):
        raise TypeError("Cannot convert bool to int")
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        try:
            return int(val, 16) if val.startswith("0x") else int(val)
        except ValueError:
            raise TypeError(f"Cannot convert string '{val}' to int")
    if isinstance(val, dict):
        # Handle cases where provider wraps data or returns error payload
        if "error" in val or "code" in val:
            raise ConnectionError(f"RPC returned error payload: {val}")
        if "result" in val:
            return to_int(val["result"])
    raise TypeError(f"Cannot convert {type(val)} to int")


class RpcNodesExhaustedError(RuntimeError):
    """Every node in the array failed or is cooling down."""


class RpcFailoverRouter:
    """Round-robin JSON-RPC dispatcher over an array of public endpoints."""

    def __init__(
        self,
        name: str,
        urls: list[str],
        cooldown_seconds: float = 60.0,
        timeout: float = 15.0,
    ) -> None:
        if not urls:
            raise ValueError(f"RpcFailoverRouter({name}) needs at least one URL")
        self._name = name
        self._urls = urls
        self._cooldown_seconds = cooldown_seconds
        self._timeout = timeout
        self._cooldown_until: dict[str, float] = {}
        self._rotation = itertools.cycle(range(len(urls)))
        self._client: httpx.AsyncClient | None = None

    async def post(self, payload: dict[str, Any]) -> Any:
        """Send one JSON-RPC payload, failover on unhealthy nodes.

        Raises :class:`RpcNodesExhaustedError` only when every node has been
        tried in this pass.
        """
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        now = time.monotonic()
        last_error: Exception | None = None
        # Try every node once per call; cooled-down ones are skipped instantly.
        for _ in range(len(self._urls)):
            idx = next(self._rotation)
            url = self._urls[idx]
            if self._cooldown_until.get(url, 0) > now:
                continue
            try:
                resp = await self._client.post(url, json=payload)
                if resp.status_code in _FAILOVER_STATUS:
                    self._penalize(url, f"HTTP {resp.status_code}")
                    last_error = RuntimeError(f"{url} returned {resp.status_code}")
                    continue
                resp.raise_for_status()
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as e:
                self._penalize(url, type(e).__name__)
                last_error = e
                continue
            try:
                body = resp.json()
            except ValueError as e:
                self._penalize(url, "non-json response")
                last_error = e
                continue
            if "error" in body:
                err = body["error"]
                if _is_node_capacity_error(err):
                    # Node policy/capacity limit — rotate to the next node.
                    self._penalize(url, f"RPC {err.get('code')}")
                    last_error = RuntimeError(f"RPC error from {url}: {err}")
                    continue
                # Genuine param/protocol error: the node is healthy — surface it
                # instead of burning the array on a request that can't succeed.
                raise RuntimeError(f"RPC error from {url}: {err}")
            return body.get("result")
        raise RpcNodesExhaustedError(f"{self._name}: all nodes failed") from last_error

    def _penalize(self, url: str, reason: str) -> None:
        until = time.monotonic() + self._cooldown_seconds
        self._cooldown_until[url] = max(self._cooldown_until.get(url, 0), until)
        log.warning("rpc_node_cooldown", extra={"router": self._name, "node": url, "reason": reason})

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def split_urls(raw: str | None) -> list[str]:
    """Comma-separated env string -> clean URL list."""
    return [u.strip() for u in (raw or "").split(",") if u.strip()]
