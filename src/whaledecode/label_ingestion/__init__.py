"""Automated ingestion pipeline for public EVM address labels.

Ingests, normalizes and stores EVM address labels (name tags / entities /
categories) from public GitHub repositories, with first-class support for
Ethereum (1), Arbitrum (42161) and Base (8453).

Modules
-------
github_client : async GitHub API client (rate-limited, retrying, PAT-aware)
parsers       : file-type + per-repo extractors -> raw label dicts
normalizer    : EIP-55 checksum + Pydantic unification + cross-chain flagging
storage       : SQLite upsert store with lookup indexes
main          : orchestration + CLI (`python -m evm_label_pipeline.main`)
"""
from __future__ import annotations

from whaledecode.label_ingestion.normalizer import (
    CROSS_CHAIN_REPLICATE,
    SUPPORTED_CHAIN_IDS,
    AddressLabel,
    flag_cross_chain,
    is_valid_address,
    normalize,
)
from whaledecode.label_ingestion.storage import LabelStore

__all__ = [
    "AddressLabel",
    "CROSS_CHAIN_REPLICATE",
    "SUPPORTED_CHAIN_IDS",
    "LabelStore",
    "flag_cross_chain",
    "is_valid_address",
    "normalize",
]
