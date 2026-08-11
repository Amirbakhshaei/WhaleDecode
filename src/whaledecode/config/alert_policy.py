"""Anti-fatigue publishing policy: per-chain thresholds, dedupe windows, and global caps.

`GlobalAntiFatiguePolicy` caps channel volume so a single whale campaign never
spams subscribers; the black-swan override lets $2M+ moves bypass the hourly cap.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChainPolicy:
    chain_code: str
    min_usd_threshold: float
    min_score_to_publish: float
    cluster_dedupe_window_sec: int
    token_dedupe_window_sec: int
    max_daily_alerts: int


@dataclass(frozen=True)
class GlobalAntiFatiguePolicy:
    max_alerts_per_hour: int = 3
    max_alerts_per_day: int = 15
    black_swan_usd_override: float = 2_000_000.0  # Bypass hourly caps for $2M+ moves


# Production Parameter Matrix
CHAIN_POLICIES: dict[str, ChainPolicy] = {
    "ETH": ChainPolicy(
        chain_code="ETH",
        min_usd_threshold=500_000.0,  # $500k USD floor
        min_score_to_publish=75.0,  # High conviction only
        cluster_dedupe_window_sec=1800,  # 30-minute cluster suppression
        token_dedupe_window_sec=3600,  # 1-hour token suppression
        max_daily_alerts=4,
    ),
    "ARB": ChainPolicy(
        chain_code="ARB",
        min_usd_threshold=75_000.0,  # $75k USD floor
        min_score_to_publish=70.0,
        cluster_dedupe_window_sec=900,  # 15-minute cluster suppression
        token_dedupe_window_sec=1800,  # 30-minute token suppression
        max_daily_alerts=3,
    ),
    "BASE": ChainPolicy(
        chain_code="BASE",
        min_usd_threshold=30_000.0,  # $30k USD floor for high-velocity alts
        min_score_to_publish=65.0,
        cluster_dedupe_window_sec=600,  # 10-minute cluster suppression
        token_dedupe_window_sec=900,  # 15-minute token suppression
        max_daily_alerts=5,
    ),
}

GLOBAL_POLICY = GlobalAntiFatiguePolicy()
