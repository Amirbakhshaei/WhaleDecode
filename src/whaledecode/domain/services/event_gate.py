"""Deterministic pre-LLM filter for candidate events."""
import logging
from typing import Any

from whaledecode.adapters.chain.normalizer import transfer_amount
from whaledecode.domain.entities.candidate_event import CandidateEvent

logger = logging.getLogger(__name__)

CRITICAL_EVENT_TYPES = {"SUSPICIOUS_CONTRACT_CREATION", "FLASH_LOAN_ATTACK", "LARGE_LIQUIDATION"}

# Un-bypassable floor: an event must clear a confirmed $50k USD value before any
# scoring or LLM logic runs. Blocks dust, approvals, and $0.00 spam.
MIN_WHALE_THRESHOLD_USD = 50_000.0

STABLECOINS = {"USDC", "USDT", "DAI", "FRAX", "TUSD", "USDP", "FDUSD"}

# CandidateEvent.chain / raw_json fields used to resolve the token being moved.
_ASSET_KEYS = ("asset", "symbol", "token", "tokenSymbol")
_TOKEN_AMOUNT_KEYS = ("token_amount", "amount")


async def process_and_gate_candidate(candidate: CandidateEvent, price_oracle: Any, timestamp: float | None = None) -> bool:
    """Compute the event's *true* USD value and enforce the whale floor.

    Overrides ``raw_json["value_usd"]`` with the oracle-derived amount before any
    scoring or LLM logic runs. Returns ``True`` when the event clears the $50k
    floor; otherwise marks it ``skipped`` with score ``0.0`` and returns ``False``.

    ``price_oracle`` needs a ``get_token_price_usd_at(contract_address, chain, unix_ts)``
    method returning a ``float`` USD unit price (``0.0`` = unknown); when
    ``timestamp`` is ``None`` it falls back to ``get_token_price_usd(...)``.
    """
    raw = candidate.raw_json if isinstance(candidate.raw_json, dict) else {}
    contract_address = raw.get("address") or raw.get("contract_address") or ""
    token_amount = _coerce_float_if_present(_first_present(raw, _TOKEN_AMOUNT_KEYS)) or transfer_amount(raw)
    asset = str(_first_present(raw, _ASSET_KEYS) or "").upper()

    if timestamp is not None:
        unit_price = await price_oracle.get_token_price_usd_at(contract_address=contract_address, chain=candidate.chain, unix_ts=timestamp)
    else:
        unit_price = await price_oracle.get_token_price_usd(contract_address=contract_address, chain=candidate.chain)
    if unit_price > 0.0:
        value_usd = token_amount * unit_price
    elif asset in STABLECOINS:
        value_usd = token_amount
    else:
        value_usd = 0.0

    candidate.raw_json["value_usd"] = value_usd
    if value_usd < MIN_WHALE_THRESHOLD_USD:
        logger.debug(f"Event {candidate.tx_hash} dropped: value ${value_usd:,.2f} < ${MIN_WHALE_THRESHOLD_USD:,.0f}")
        candidate.status = "skipped"
        candidate.score = 0.0
        return False
    return True


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


def _first_present(raw: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """Return the first non-empty value among ``keys``, or ``None``."""
    for key in keys:
        value = raw.get(key)
        if value is not None and value != "":
            return value
    return None
