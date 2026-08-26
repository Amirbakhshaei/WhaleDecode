"""Ingestion-time validation for candidate events.

The single gate that keeps malformed payloads (e.g. truncated EVM tx hashes)
out of ``candidate_events`` at the poller boundary, before they can become
poison pills that fail hydration downstream.
"""
import re

from pydantic import BaseModel, ValidationInfo, field_validator

# EVM chains by code or label (ingestion stores both forms across pollers).
EVM_CHAIN_IDS = {"ETH", "BASE", "ARB", "BSC", "POLYGON", "ETHEREUM", "ARBITRUM"}

HEX_32_BYTE_REGEX = re.compile(r"^0x[a-fA-F0-9]{64}$")


class IngestCandidateEventDTO(BaseModel):
    # `chain` must precede `tx_hash`: pydantic validates fields in declaration
    # order, so the tx_hash validator can read the resolved chain from info.data.
    chain: str
    tx_hash: str

    @field_validator("tx_hash")
    @classmethod
    def validate_tx_hash(cls, v: str, info: ValidationInfo) -> str:
        chain = (info.data.get("chain") or "").upper()
        if chain in EVM_CHAIN_IDS and not HEX_32_BYTE_REGEX.match(v):
            raise ValueError(f"Malformed EVM 32-byte hash: {v} (length: {len(v)})")
        return v


def is_valid_ingest_hash(tx_hash: str, chain: str) -> bool:
    """Boolean wrapper for callers that want to skip-and-log rather than raise."""
    try:
        IngestCandidateEventDTO(tx_hash=tx_hash, chain=chain)
        return True
    except ValueError:
        return False
