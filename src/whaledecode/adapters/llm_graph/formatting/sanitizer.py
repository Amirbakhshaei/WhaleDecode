"""Strips RPC protocol noise to produce an ultra-compact dict for LLM context."""
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
