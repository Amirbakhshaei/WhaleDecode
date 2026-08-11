from datetime import UTC, datetime
from typing import Any

# Standard ERC-20 Transfer(address indexed from, address indexed to, uint256 value)
TRANSFER_EVENT_SIGNATURE = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def pad_address_to_topic(address: str) -> str:
    """Pad a 20-byte address to the 32-byte padded form used in log topics.

    ``0x123...`` → ``0x000000000000000000000000123...`` (64 hex chars).
    """
    body = address[2:] if address.lower().startswith("0x") else address
    return "0x" + body.lower().zfill(64)


def wallet_id_from_transfer_topics(topics: list[str], padded_to_wallet_id: dict[str, int]) -> int | None:
    """Map a Transfer log's topics back to a tracked wallet, if either the
    ``from`` (topics[1]) or ``to`` (topics[2]) side is one of our wallets."""
    for idx in (1, 2):
        if idx < len(topics) and topics[idx]:
            wallet_id = padded_to_wallet_id.get(topics[idx].lower())
            if wallet_id is not None:
                return wallet_id
    return None


def normalize_log(raw_log: dict[str, Any], wallet_id: int, chain: str) -> dict[str, Any]:
    tx_hash = raw_log.get("transactionHash", "")
    log_index = raw_log.get("logIndex", 0)
    if isinstance(log_index, str):
        log_index = int(log_index, 16)
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
    swap_sig = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
    approval_sig = "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"
    if sig == TRANSFER_EVENT_SIGNATURE:
        return "TRANSFER"
    if sig == swap_sig:
        return "SWAP"
    if sig == approval_sig:
        return "APPROVE"
    return "CONTRACT_INTERACTION"


def transfer_amount(raw_log: dict[str, Any], decimals: int = 18) -> float:
    """Decode an ERC-20 Transfer log's ``data`` field into a token amount.

    Returns ``0.0`` when the amount is missing or unparseable. Defaults to 18
    decimals; pass the real contract decimals when known (see ``parse_token_amount``).
    """
    return parse_token_amount(raw_log.get("data", "0x0"), decimals)


def parse_token_amount(raw_hex_value: str, decimals: int) -> float:
    """Decode a raw hex token amount to its human-readable quantity.

    ``decimals`` must come from the token contract — deterministic scaling.
    Guessing 18 for a 6-decimal token (USDC/USDT/DAI) would inflate the value
    by 10^12, which is exactly the valuation anomaly this avoids.
    """
    if not raw_hex_value or raw_hex_value == "0x":
        return 0.0
    try:
        return int(raw_hex_value, 16) / (10**decimals)
    except (TypeError, ValueError):
        return 0.0


def _estimate_value(raw_log: dict[str, Any], event_type: str) -> float:
    if event_type == "TRANSFER":
        return transfer_amount(raw_log)
    return 0.0
