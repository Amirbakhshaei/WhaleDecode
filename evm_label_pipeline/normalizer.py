"""Normalization & validation layer: EIP-55, Pydantic unification, cross-chain flagging."""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator
from web3 import Web3

from evm_label_pipeline.config import CROSS_CHAIN_REPLICATE, CROSS_EVM, SUPPORTED_CHAIN_IDS

ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

# Flexible key aliases -> canonical AddressLabel field. Lets heterogeneous repo
# schemas (address / contract_address / token_address ...) map without per-repo code.
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "address": ("address", "contract_address", "token_address", "wallet", "address_hash", "addr"),
    "chain_id": ("chain_id", "chainid", "chainId", "network", "chain"),
    "name_tag": ("name_tag", "name", "label", "tag", "display_name", "namestring"),
    "entity": ("entity", "project", "protocol", "owner", "exchange"),
    "category": ("category", "type", "label_type", "tag_type", "kind"),
    "source": ("source", "src"),
    "confidence_score": ("confidence_score", "confidence", "score", "weight"),
}


class AddressLabel(BaseModel):
    """Unified, validated EVM address label schema."""

    address: str  # EIP-55 checksummed 0x...
    chain_id: int  # 1 / 42161 / 8453 / 0 (cross-EVM)
    name_tag: str
    entity: str = ""
    category: str = "Unknown"
    source: str = ""
    confidence_score: float = Field(default=0.5, ge=0.0, le=1.0)
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @field_validator("address")
    @classmethod
    def _checksum_address(cls, v: str) -> str:
        return Web3.to_checksum_address(v)

    @field_validator("chain_id")
    @classmethod
    def _known_chain(cls, v: int) -> int:
        if v not in SUPPORTED_CHAIN_IDS:
            raise ValueError(f"unsupported chain_id {v!r}; expected one of {sorted(SUPPORTED_CHAIN_IDS)}")
        return v


def is_valid_address(value: str) -> bool:
    """Fast syntactic check before attempting (expensive) checksumming."""
    return bool(ADDRESS_RE.match(value or ""))


def _remap(raw: dict[str, Any]) -> dict[str, Any]:
    """Collapse heterogeneous input keys onto the canonical AddressLabel field names."""
    lowered = {k.lower(): v for k, v in raw.items() if v not in (None, "")}
    out: dict[str, Any] = {}
    for canonical, aliases in _FIELD_ALIASES.items():
        for alias in aliases:
            if alias in lowered:
                out[canonical] = lowered[alias]
                break
    return out


def _coerce_chain_id(value: Any) -> int:
    if value is None:
        return CROSS_EVM
    if isinstance(value, str):
        value = value.strip().lower()
        if value in ("", "all", "cross", "evm", "*"):
            return CROSS_EVM
        # "ethereum" -> 1, "arbitrum" -> 42161, "base" -> 8453
        _names = {"ethereum": 1, "arb": 42161, "arbitrum": 42161, "base": 8453, "cross-evm": 0}
        if value in _names:
            return _names[value]
        try:
            value = int(value)
        except ValueError as exc:
            raise ValueError(f"unparseable chain_id {value!r}") from exc
    return int(value)


def _coerce_confidence(value: Any) -> float:
    if value is None:
        return 0.5
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, score))


def normalize(raw: dict[str, Any], source: str = "") -> AddressLabel | None:
    """Validate + unify one raw record into an :class:`AddressLabel`.

    Returns ``None`` when the record lacks a usable address or fails validation
    (e.g. non-EVM hex, unsupported chain). Never raises for bad data — callers
    iterate over many records, so silent skip + count is the right contract.
    """
    if not raw:
        return None
    mapped = _remap(raw)

    addr = mapped.get("address")
    if not is_valid_address(addr):
        return None

    try:
        return AddressLabel(
            address=addr,
            chain_id=_coerce_chain_id(mapped.get("chain_id")),
            name_tag=str(mapped.get("name_tag") or mapped.get("entity") or addr),
            entity=str(mapped.get("entity") or ""),
            category=str(mapped.get("category") or "Unknown"),
            source=str(mapped.get("source") or source or ""),
            confidence_score=_coerce_confidence(mapped.get("confidence_score")),
        )
    except (ValidationError, ValueError):
        return None


def flag_cross_chain(label: AddressLabel) -> list[AddressLabel]:
    """Replicate chain-agnostic labels (CEX/Bridge/Protocol/...) across L1/L2.

    A Binance hot wallet or a Uniswap deployer is the *same* address on Ethereum,
    Arbitrum and Base, so we emit one label per chain. Chain-specific or per-chain
    token labels are returned unchanged.
    """
    if label.category not in CROSS_CHAIN_REPLICATE:
        return [label]
    return [
        label.model_copy(update={"chain_id": chain_id}) for chain_id in (1, 42161, 8453)
    ]
