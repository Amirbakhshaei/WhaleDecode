"""Asymmetric Anomaly & Conviction Scoring (Module 3).

Deterministic domain math — no I/O. Replaces flat dollar thresholds with
liquidity-relative metrics:

* ``pool_impact_ratio``: trade USD / DEX pool TVL. A $8k buy in a $400k pool
  is more informative than a $500k buy in a $200M pool.
* ``coordinated_accumulation``: >= N independent smart-money wallets buying
  the same token within a rolling window across EVM chains.
"""
from dataclasses import dataclass, field
from typing import Any

POOL_IMPACT_FLAG_THRESHOLD = 0.015  # absorb >= 1.5% of pool depth
COORDINATION_WINDOW_MINUTES = 60
COORDINATION_MIN_WALLETS = 2
COORDINATION_BADGE = "🔥 Coordinated Whale Accumulation"
CRITICAL_PRIORITY = "CRITICAL"


def pool_impact_ratio(trade_usd: float, pool_tvl_usd: float) -> float:
    """R_pool = Trade USD / Pool TVL. 0.0 when TVL unknown (conservative)."""
    if pool_tvl_usd <= 0:
        return 0.0
    return abs(trade_usd) / pool_tvl_usd


@dataclass(frozen=True)
class PoolImpactVerdict:
    ratio: float
    flagged: bool


def evaluate_pool_impact(trade_usd: float, pool_tvl_usd: float) -> PoolImpactVerdict:
    """Flag any purchase absorbing >= POOL_IMPACT_FLAG_THRESHOLD of pool depth."""
    ratio = pool_impact_ratio(trade_usd, pool_tvl_usd)
    return PoolImpactVerdict(ratio=round(ratio, 6), flagged=ratio >= POOL_IMPACT_FLAG_THRESHOLD)


@dataclass(frozen=True)
class Purchase:
    wallet_address: str
    token_address: str
    chain: str
    timestamp_unix: float


@dataclass(frozen=True)
class CoordinationVerdict:
    coordinated: bool
    distinct_wallets: int
    badge: str = ""


def detect_coordinated_accumulation(
    purchases: list[Purchase],
    now_unix: float,
    *,
    window_minutes: int = COORDINATION_WINDOW_MINUTES,
    min_wallets: int = COORDINATION_MIN_WALLETS,
    smart_wallets: set[str] | None = None,
) -> CoordinationVerdict:
    """Detect >= ``min_wallets`` distinct smart wallets buying the same token
    within the rolling window — across chains (ETH/Base/Arbitrum purchases of
    the same contract count together per spec). Wallets must be independent
    (distinct addresses); when ``smart_wallets`` is given only those count."""
    smart = {w.lower() for w in (smart_wallets or set())}
    cutoff = now_unix - window_minutes * 60
    by_token: dict[str, set[str]] = {}
    for p in purchases:
        if p.timestamp_unix < cutoff or p.timestamp_unix > now_unix:
            continue
        wallet = p.wallet_address.lower()
        if smart and wallet not in smart:
            continue
        by_token.setdefault(p.token_address.lower(), set()).add(wallet)

    best = max((len(v) for v in by_token.values()), default=0)
    coordinated = best >= min_wallets
    return CoordinationVerdict(
        coordinated=coordinated,
        distinct_wallets=best,
        badge=COORDINATION_BADGE if coordinated else "",
    )


@dataclass
class ConvictionResult:
    priority: str = "normal"
    badges: list[str] = field(default_factory=list)
    pool_impact_ratio: float = 0.0
    pool_impact_flagged: bool = False
    coordinated_wallets: int = 0

    def to_context(self) -> dict[str, Any]:
        ctx: dict[str, Any] = {
            "pool_impact_ratio_pct": round(self.pool_impact_ratio * 100, 3),
            "pool_impact_flagged": self.pool_impact_flagged,
            "priority": self.priority,
        }
        if self.badges:
            ctx["badges"] = self.badges
        if self.coordinated_wallets:
            ctx["coordinated_smart_wallets"] = self.coordinated_wallets
        return ctx


def score_conviction(
    trade_usd: float,
    pool_tvl_usd: float,
    purchases: list[Purchase],
    now_unix: float,
    *,
    smart_wallets: set[str] | None = None,
) -> ConvictionResult:
    """One-call deterministic scorer used by the investigation pipeline."""
    impact = evaluate_pool_impact(trade_usd, pool_tvl_usd)
    coord = detect_coordinated_accumulation(
        purchases, now_unix, smart_wallets=smart_wallets
    )
    result = ConvictionResult(
        pool_impact_ratio=impact.ratio,
        pool_impact_flagged=impact.flagged,
        coordinated_wallets=coord.distinct_wallets,
    )
    if coord.coordinated:
        result.priority = CRITICAL_PRIORITY
        result.badges.append(coord.badge)
    elif impact.flagged:
        result.priority = CRITICAL_PRIORITY
        result.badges.append(f"🎯 Absorbs {result.pool_impact_ratio}% of pool liquidity")
    return result
