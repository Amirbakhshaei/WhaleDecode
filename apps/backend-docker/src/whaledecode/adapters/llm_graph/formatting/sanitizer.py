"""Strips RPC protocol noise and prompt scaffolding for clean LLM/Telegram output."""
import re
from typing import Any

KEYS_TO_IGNORE = {
    "blockHash",
    "blockNumber",
    "transactionIndex",
    "cumulativeGasUsed",
    "effectiveGasPrice",
    "logsBloom",
    "status",
    "type",
    "v",
    "r",
    "s",
}


def sanitize_event_payload(raw_json: dict) -> dict:
    """Compact raw RPC event data, dropping protocol noise and trimming long lists."""
    compact_payload: dict[str, Any] = {}
    for key, value in raw_json.items():
        if key in KEYS_TO_IGNORE:
            continue
        if isinstance(value, list) and len(value) > 10:
            compact_payload[key] = value[:5]  # Keep first 5 items
        else:
            compact_payload[key] = value
    return compact_payload


def strip_prompt_artifacts(text: str) -> str:
    """Removes leftover prompt scaffolding like [Label:], [], and + signs.

    Applied as a final safety net before Telegram dispatch so model output that
    slips a template fragment (e.g. '[Vector: CEX Outflow] + [Entity Route]') or
    an 'N/A' sentinel never reaches traders.
    """
    # Remove leading bracketed labels like '[CEX/MM Inflow]:' or '[Vector: ...]:'
    cleaned = re.sub(r"\[.*?:\s*", "", text)
    cleaned = cleaned.replace("[", "").replace("]", "")
    # Remove dangling plus signs between phrases
    cleaned = re.sub(r"\s+\+\s+", " ", cleaned)
    # Remove literal 'N/A' mentions
    cleaned = re.sub(r"\bN/A\b", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()
