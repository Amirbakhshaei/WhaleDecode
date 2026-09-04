"""Chain-aware resilient RPC dispatch.

Built on top of ``whaledecode.infrastructure.rpc_router.RpcFailoverRouter``,
which already does round-robin over weighted endpoints, 60-second cooldowns on
429/502/503/504/520-524 / JSON-RPC capacity errors, and httpx transport with
timeouts. This wrapper adds the two behaviours the pool spec calls for:

* **Chain-level circuit breaker** — after ``breaker_threshold`` consecutive
  ``RpcNodesExhaustedError`` raises on one chain, quarantine the whole chain
  for ``cooldown_seconds`` instead of hammering it again immediately. (The
  per-node cooldown is the existing router's job.)
* **Transparent retry decorator** — ``execute()`` retries up to
  ``max_retries`` times with jittered exponential backoff, each retry going
  through the router (which itself rotates to the next healthy node).
* **Chain-keyed fan-out** — one manager owns one ``RpcFailoverRouter`` per
  chain. Callers say ``await mgr.execute("base", payload)`` and the right
  router answers.

Why a wrapper and not a reimplementation: the existing
``RpcFailoverRouter`` is on the hot path of the poller and is regression-tested
(``tests/unit/infrastructure/test_targeted_poller.py``). Duplicating its
logic would re-open every bug fix the existing router has earned.
"""
from __future__ import annotations

import asyncio
import random
import time
from typing import Any

import structlog
from whaledecode.infrastructure.rpc_router import (
    RpcFailoverRouter,
    RpcNodesExhaustedError,
    split_urls,
)
from whaledecode.pools.config.loader import get_chain, get_chains

log = structlog.get_logger()

DEFAULT_BREAKER_THRESHOLD = 3
DEFAULT_COOLDOWN_SECONDS = 60.0
DEFAULT_MAX_RETRIES = 5
DEFAULT_TIMEOUT = 15.0
MAX_BACKOFF_SECONDS = 8.0


class CircuitOpenError(RuntimeError):
    """Raised when every node is in cooldown AND the breaker is still open."""


class ResilientRPCManager:
    """Per-chain RPC dispatch with a chain-level circuit breaker + retry.

    ponytail: reuses ``RpcFailoverRouter`` for transport so the existing poller
    stays unchanged. add when the breaker logic needs to be applied to the
    poller too — then promote breaker state to a shared module.
    """

    def __init__(
        self,
        chains: list[str] | None = None,
        breaker_threshold: int = DEFAULT_BREAKER_THRESHOLD,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._breaker_threshold = breaker_threshold
        self._cooldown_seconds = cooldown_seconds
        self._max_retries = max_retries
        self._timeout = timeout
        self._routers: dict[str, RpcFailoverRouter] = {}
        self._consecutive_failures: dict[str, int] = {}
        self._breaker_open_until: dict[str, float] = {}
        # ``chains`` is a hint: if the name is in chains.yaml, auto-register
        # it from the configured URLs. Tests using fake chains should call
        # ``register_chain()`` instead.
        if chains is not None:
            known = set(get_chains().keys())
            for name in chains:
                if name in known:
                    cfg = get_chain(name)
                    self.register_chain(name, urls=[u for u, _w in cfg.rpc_urls])

    @classmethod
    def from_config(cls, chains: list[str] | None = None, **kwargs: Any) -> ResilientRPCManager:
        names = chains or list(get_chains().keys())
        return cls(chains=names, **kwargs)

    def register_chain(self, name: str, urls: list[str]) -> None:
        """Test/extension hook — register a custom URL list for a chain."""
        self._routers[name] = RpcFailoverRouter(
            name=name,
            urls=urls,
            cooldown_seconds=self._cooldown_seconds,
            timeout=self._timeout,
        )
        self._consecutive_failures.setdefault(name, 0)
        self._breaker_open_until.setdefault(name, 0.0)

    def chains(self) -> list[str]:
        return list(self._routers.keys())

    async def execute(self, chain: str, payload: dict[str, Any]) -> Any:
        """Run a JSON-RPC payload against the named chain with retry + breaker.

        Raises :class:`CircuitOpenError` if the chain's breaker is open.
        Raises :class:`RpcNodesExhaustedError` after all retries are exhausted
        if every node in the chain's router is cooling down.
        """
        router = self._routers.get(chain)
        if router is None:
            raise KeyError(f"No router registered for chain={chain}")

        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            if self._breaker_open_until.get(chain, 0.0) > time.monotonic():
                # Wait up to 5 s before giving up; the underlying router's
                # per-node cooldowns may have already cleared some endpoints.
                wait_for = self._breaker_open_until[chain] - time.monotonic()
                await asyncio.sleep(min(max(wait_for, 0.0), 5.0))
                raise CircuitOpenError(f"{chain}: circuit breaker open")
            try:
                result = await router.post(payload)
                self._on_success(chain)
                return result
            except RpcNodesExhaustedError as e:
                last_exc = e
                self._on_failure(chain)
                backoff = min(0.5 * (2 ** attempt), MAX_BACKOFF_SECONDS) * random.uniform(0.5, 1.0)
                await asyncio.sleep(backoff)
        raise last_exc or CircuitOpenError(f"{chain}: exhausted retries")

    def _on_success(self, chain: str) -> None:
        self._consecutive_failures[chain] = 0
        self._breaker_open_until[chain] = 0.0

    def _on_failure(self, chain: str) -> None:
        streak = self._consecutive_failures.get(chain, 0) + 1
        self._consecutive_failures[chain] = streak
        if streak >= self._breaker_threshold:
            until = time.monotonic() + self._cooldown_seconds
            self._breaker_open_until[chain] = max(self._breaker_open_until.get(chain, 0.0), until)
            log.warning(
                "rpc_breaker_open",
                extra={"chain": chain, "streak": streak, "cooldown": self._cooldown_seconds},
            )

    def breaker_state(self, chain: str) -> dict[str, Any]:
        """For tests / observability: is the breaker open, since when, etc."""
        return {
            "chain": chain,
            "consecutive_failures": self._consecutive_failures.get(chain, 0),
            "open_until": self._breaker_open_until.get(chain, 0.0),
            "open": self._breaker_open_until.get(chain, 0.0) > time.monotonic(),
        }

    async def aclose(self) -> None:
        await asyncio.gather(
            *(router.aclose() for router in self._routers.values()),
            return_exceptions=True,
        )


# Re-exports for callers — domain code shouldn't reach into infrastructure.
__all__ = [
    "CircuitOpenError",
    "DEFAULT_BREAKER_THRESHOLD",
    "DEFAULT_COOLDOWN_SECONDS",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_TIMEOUT",
    "ResilientRPCManager",
    "split_urls",
]
