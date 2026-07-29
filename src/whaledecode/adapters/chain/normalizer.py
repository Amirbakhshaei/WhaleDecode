from datetime import UTC, datetime
from typing import Any


def normalize_log(raw_log: dict[str, Any], wallet_id: int, chain: str) -> dict[str, Any]:
    tx_hash = raw_log.get("transactionHash", "")
    log_index = raw_log.get("logIndex", 0)
    block_number = raw_log.get("blockNumber", 0)
    if isinstance(block_number, str):
        block_number = int(block_number, 16)

    address = raw_log.get("address", "")
    topics = raw_log.get("topics", [])

    event_type = _classify_event(topics, address)
    value_usd = _estimate_value(raw_log, event_type)

    return {
        "wallet_id": wallet_id,
        "chain": chain,
        "tx_hash": tx_hash,
        "log_index": log_index,
        "block_number": block_number,
        "event_type": event_type,
        "value_usd": value_usd,
        "raw_json": raw_log,
        "dedupe_key": f"{wallet_id}:{tx_hash}:{log_index}",
        "created_at": datetime.now(UTC),
    }


def dedupe_key(wallet_id: int, tx_hash: str, log_index: int) -> str:
    return f"{wallet_id}:{tx_hash}:{log_index}"


def _classify_event(topics: list[str], address: str) -> str:
    if not topics:
        return "CONTRACT_INTERACTION"
    sig = topics[0] if topics else ""
    transfer_sig = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    swap_sig = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
    approval_sig = "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"
    if sig == transfer_sig:
        return "TRANSFER"
    if sig == swap_sig:
        return "SWAP"
    if sig == approval_sig:
        return "APPROVE"
    return "CONTRACT_INTERACTION"


def _estimate_value(raw_log: dict[str, Any], event_type: str) -> float:
    if event_type == "TRANSFER":
        data = raw_log.get("data", "0x0")
        if len(data) > 2 and data != "0x0":
            try:
                val = int(data, 16)
                return val / 1e18
            except (ValueError, TypeError):
                pass
    return 0.0
