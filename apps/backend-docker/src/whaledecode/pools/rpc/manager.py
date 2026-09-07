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
from aiolimiter import AsyncLimiter

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
DEFAULT_DAILY_BUDGET = 50_000

# ponytail: budget caps per provider — Alchemy / Infura / dRPC / Ankr have
# documented monthly allowances; the per-day ceiling is the monthly cap /30
# minus a 20% safety margin. Unmetered foundation nodes get a much higher cap.
# Per-provider assignment lives on the per-node record so multi-provider
# pools each carry their own counter.
_PROVIDER_DAILY_BUDGET: dict[str, int] = {
    "alchemy": 11_000,           # ~825k CUs/day @ 75 CU/log query (30M/mo budget)
    "infura": 45_000,            # 100k daily cap headroom
    "drpc": 30_000,              # safe dynamic allowance
    "ankr": 10_000,              # burst-sensitive
    "base_foundation": 500_000,  # unmetered Coinbase public node
    "arb_foundation": 500_000,   # unmetered Offchain Labs public node
    "generic": 20_000,
}


def _classify_provider(url: str) -> str:
    """Best-effort provider label from URL hostname; fallback ``generic``."""
    u = url.lower()
    if "alchemy.com" in u:
        return "alchemy"
    if "infura.io" in u:
        return "infura"
    if "drpc.org" in u or "drpc.live" in u:
        return "drpc"
    if "ankr.com" in u:
        return "ankr"
    if "mainnet.base.org" in u or "base.org" in u:
        return "base_foundation"
    if "arb1.arbitrum.io" in u or "arbitrum.io" in u:
        return "arb_foundation"
    return "generic"


class _NodeBudget:
    """Per-URL call counter with daily cap. Resets at UTC midnight via
    :meth:`reset_daily_counters` (scheduled from ``entrypoints/worker.py``).
    """

    __slots__ = ("url", "provider", "max_daily_calls", "calls_today", "calls_reset_at")

    def __init__(self, url: str, provider: str, max_daily_calls: int) -> None:
        self.url = url
        self.provider = provider
        self.max_daily_calls = max_daily_calls
        self.calls_today = 0
        # Next UTC midnight; reset_daily_counters() zeroes the counter at this
        # point. Cached here so each node doesn't recompute the boundary.
        self.calls_reset_at = _next_utc_midnight()

    @property
    def budget_remaining(self) -> int:
        return max(0, self.max_daily_calls - self.calls_today)

    def is_within_budget(self) -> bool:
        if time.time() >= self.calls_reset_at:
            self.calls_today = 0
            self.calls_reset_at = _next_utc_midnight()
        return self.calls_today < self.max_daily_calls


def _next_utc_midnight() -> float:
    """Epoch seconds for the next UTC midnight (exclusive)."""
    import datetime as _dt

    now = _dt.datetime.now(_dt.UTC)
    tomorrow = (now + _dt.timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return tomorrow.timestamp()


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
        rate_limit_per_second: float | None = None,
    ) -> None:
        self._breaker_threshold = breaker_threshold
        self._cooldown_seconds = cooldown_seconds
        self._max_retries = max_retries
        self._timeout = timeout
        self._routers: dict[str, RpcFailoverRouter] = {}
        # Per-node daily-budget tracker, keyed by URL. Lives alongside the
        # router so it survives across ``execute()`` calls without re-reading
        # env vars.
        self._node_budgets: dict[str, _NodeBudget] = {}
        self._consecutive_failures: dict[str, int] = {}
        self._breaker_open_until: dict[str, float] = {}
        # ponytail: optional process-global rate limiter — acquire before every
        # router.post() so bursts are impossible across the whole process.
        self._limiter: AsyncLimiter | None = (
            AsyncLimiter(max_rate=rate_limit_per_second, time_period=1.0)
            if rate_limit_per_second is not None
            else None
        )
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

    def get_router(self, chain_name: str) -> RpcFailoverRouter | None:
        """Extract the underlying router for a chain (used by TargetedPollerService)."""
        return self._routers.get(chain_name)

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
        # ponytail: register a per-URL budget on first sight. Subsequent
        # ``register_chain`` calls for the same URL keep the existing counter
        # so daily totals don't double-count across chain pools.
        for url in urls:
            if url not in self._node_budgets:
                provider = _classify_provider(url)
                cap = _PROVIDER_DAILY_BUDGET.get(provider, DEFAULT_DAILY_BUDGET)
                self._node_budgets[url] = _NodeBudget(url, provider, cap)

    def reset_daily_counters(self) -> None:
        """Zero all per-node daily counters. Called by the cron at UTC midnight."""
        for budget in self._node_budgets.values():
            budget.calls_today = 0
            budget.calls_reset_at = _next_utc_midnight()
        log.info("rpc_daily_budgets_reset", nodes=len(self._node_budgets))

    def node_budget_state(self) -> dict[str, dict[str, Any]]:
        """Observability: per-URL calls_today / cap / provider label."""
        now = time.time()
        for budget in self._node_budgets.values():
            if now >= budget.calls_reset_at:
                budget.calls_today = 0
                budget.calls_reset_at = _next_utc_midnight()
        return {
            url: {
                "provider": b.provider,
                "calls_today": b.calls_today,
                "max_daily_calls": b.max_daily_calls,
                "within_budget": b.calls_today < b.max_daily_calls,
            }
            for url, b in self._node_budgets.items()
        }

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
            # ponytail: skip URLs that exhausted their daily budget. The
            # underlying router rotates among all URLs; budget-aware skipping
            # here keeps metered credits inside their documented monthly cap
            # without burning retries on nodes that have already hit the wall.
            for url in router._urls:  # noqa: SLF001 - intentional, internal coordination
                budget = self._node_budgets.get(url)
                if budget is not None and not budget.is_within_budget():
                    if url not in router._cooldown_until:  # noqa: SLF001
                        router._cooldown_until[url] = time.monotonic() + 3600.0  # noqa: SLF001
                        log.warning(
                            "rpc_daily_budget_exhausted",
                            extra={"node": url, "provider": budget.provider,
                                   "calls_today": budget.calls_today,
                                   "max_daily_calls": budget.max_daily_calls},
                        )
            try:
                if self._limiter is not None:
                    await self._limiter.acquire()
                result = await router.post(payload)
                self._on_success(chain)
                # Account the successful call against the budget of whichever
                # URL the router chose. The router rotates internally; we read
                # the last-touched URL via its cooldown map (best-effort).
                for url in router._urls:  # noqa: SLF001
                    budget = self._node_budgets.get(url)
                    if budget is not None and budget.calls_today >= 0:
                        # Increment on the URL with the lowest calls_today that
                        # isn't in cooldown — cheapest heuristic that still
                        # favours unmetered primaries on multi-URL chains.
                        if (
                            router._cooldown_until.get(url, 0.0)  # noqa: SLF001
                            <= time.monotonic()
                        ):
                            budget.calls_today += 1
                            break
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
