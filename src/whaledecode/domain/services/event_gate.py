"""Deterministic pre-LLM filter for candidate events."""
import logging
from typing import Any

from whaledecode.domain.entities.candidate_event import CandidateEvent

logger = logging.getLogger(__name__)

CRITICAL_EVENT_TYPES = {"SUSPICIOUS_CONTRACT_CREATION", "FLASH_LOAN_ATTACK", "LARGE_LIQUIDATION"}


class EventGate:
    def __init__(self, min_score_threshold: float = 0.65, min_value_usd: float = 5000.0) -> None:
        self.min_score_threshold = min_score_threshold
        self.min_value_usd = min_value_usd

    def should_investigate(self, event: CandidateEvent) -> bool:
        """Determines if an event warrants LLM investigation."""
        # Critical event types always pass regardless of score / value.
        if event.event_type in CRITICAL_EVENT_TYPES:
            return True

        # Filter by heuristic pre-score.
        if event.score < self.min_score_threshold:
            logger.debug(f"Event {event.tx_hash} dropped: score {event.score} < {self.min_score_threshold}")
            return False

        # Check transfer value if present in raw_json.
        value_usd = _coerce_float(event.raw_json.get("value_usd"))
        if value_usd > 0 and value_usd < self.min_value_usd:
            logger.debug(f"Event {event.tx_hash} dropped: value ${value_usd} < ${self.min_value_usd}")
            return False

        return True


def _coerce_float(value: Any) -> float:
    """RPC payloads may carry numbers as hex/string; coerce defensively."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
