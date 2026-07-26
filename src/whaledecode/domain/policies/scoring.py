"""Alert worthiness scoring formula — agents.md §7.1."""


def calculate_alert_worthiness(
    confidence: float,
    novelty_score: float,
    wallet_quality: float,
    event_type_weight: float,
    market_context_boost: float = 0.0,
) -> float:
    base = (
        0.30 * confidence
        + 0.25 * novelty_score
        + 0.25 * wallet_quality
        + 0.15 * event_type_weight
        + 0.05 * market_context_boost
    )
    return max(0.0, min(1.0, base))


TIER_THRESHOLDS = {
    "free": 0.70,
    "pro": 0.55,
    "whale": 0.40,
}

TIER_TTL_SECONDS = {
    "free": 14400,
    "pro": 7200,
    "whale": 1800,
}

TIER_DAILY_ALERT_CAP = {
    "free": 5,
    "pro": 50,
    "whale": 999,
}
