"""Deterministic pre-LLM filter for candidate events."""
import logging
from typing import Any

from whaledecode.domain.entities.candidate_event import CandidateEvent

logger = logging.getLogger(__name__)

CRITICAL_EVENT_TYPES = {"SUSPICIOUS_CONTRACT_CREATION", "FLASH_LOAN_ATTACK", "LARGE_LIQUIDATION"}

# Un-bypassable floor: an event must clear a confirmed $50k USD value before any
# scoring or LLM logic runs. Blocks dust, approvals, and $0.00 spam.
MIN_WHALE_THRESHOLD_USD = 50_000.0


class EventGate:
    def __init__(self, min_score_threshold: float = 0.65, min_value_usd: float = MIN_WHALE_THRESHOLD_USD) -> None:
        self.min_score_threshold = min_score_threshold
        self.min_value_usd = min_value_usd

    def should_investigate(self, event: CandidateEvent) -> bool:
        """Determines if an event warrants LLM investigation."""
        # Hard dollar gate: absent, zero, or sub-$50k value never reaches scoring/LLM.
        value_usd = _coerce_float_if_present(event.raw_json.get("value_usd"))
        floor = max(self.min_value_usd, MIN_WHALE_THRESHOLD_USD)
        if value_usd is None or value_usd < floor:
            logger.debug(f"Event {event.tx_hash} dropped: value ${value_usd} < ${floor}")
            return False

        # Critical event types skip the score gate, never the value gate.
        if event.event_type in CRITICAL_EVENT_TYPES:
            return True

        # Filter by heuristic pre-score.
        if event.score < self.min_score_threshold:
            logger.debug(f"Event {event.tx_hash} dropped: score {event.score} < {self.min_score_threshold}")
            return False

        return True


def _coerce_float_if_present(value: Any) -> float | None:
    """Coerce ``value_usd`` to float, or ``None`` when absent/unparseable.

    ``None`` means the value is *unknown*, and unknown is treated as below the
    whale floor — an event without a confirmed USD value is dropped.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
