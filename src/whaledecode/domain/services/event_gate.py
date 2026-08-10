"""Deterministic pre-LLM filter for candidate events."""
import logging
from typing import Any

from whaledecode.domain.entities.candidate_event import CandidateEvent

logger = logging.getLogger(__name__)

CRITICAL_EVENT_TYPES = {"SUSPICIOUS_CONTRACT_CREATION", "FLASH_LOAN_ATTACK", "LARGE_LIQUIDATION"}

# Known USD value below which an event is pure dust (approvals, contract
# interactions, spam) — never worth an LLM call.
DUST_VALUE_USD = 10.0


class EventGate:
    def __init__(self, min_score_threshold: float = 0.65, min_value_usd: float = 5000.0) -> None:
        self.min_score_threshold = min_score_threshold
        self.min_value_usd = min_value_usd

    def should_investigate(self, event: CandidateEvent) -> bool:
        """Determines if an event warrants LLM investigation."""
        # Critical event types always pass regardless of score / value.
        if event.event_type in CRITICAL_EVENT_TYPES:
            return True

        # Hard dust gate: known zero-value / sub-$10 activity never reaches the LLM.
        value_usd = _coerce_float_if_present(event.raw_json.get("value_usd"))
        if value_usd is not None and value_usd < DUST_VALUE_USD:
            logger.debug(f"Event {event.tx_hash} dropped: dust value ${value_usd} < ${DUST_VALUE_USD}")
            return False

        # Filter by heuristic pre-score.
        if event.score < self.min_score_threshold:
            logger.debug(f"Event {event.tx_hash} dropped: score {event.score} < {self.min_score_threshold}")
            return False

        # Check transfer value if present in raw_json.
        if value_usd is not None and 0 < value_usd < self.min_value_usd:
            logger.debug(f"Event {event.tx_hash} dropped: value ${value_usd} < ${self.min_value_usd}")
            return False

        return True


def _coerce_float_if_present(value: Any) -> float | None:
    """Coerce ``value_usd`` to float, or ``None`` when absent/unparseable.

    ``None`` means the value is *unknown*, not known-zero — an unknown value must
    not hard-block a high-conviction event (protects against missed whales).
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
