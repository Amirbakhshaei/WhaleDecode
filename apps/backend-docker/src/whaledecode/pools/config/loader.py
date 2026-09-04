"""Load chains.yaml + pool_seeds.json shipped next to this module.

Cached at module level so importers don't re-parse on every call. The cache is
threadsafe-enough for asyncio (single event loop = one reader at a time).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).parent

# Hard ceiling on outbound Multicall3 batch size — public nodes (notably
# Ankr) reject eth_call payloads > a few hundred KB. 100 sub-calls × ~256 B
# per header + calldata fits comfortably.
DEFAULT_MULTICALL_CHUNK = 100


@dataclass(frozen=True)
class ChainConfig:
    name: str  # "ethereum" / "arbitrum" / "base"
    chain_id: int
    multicall3: str
    rpc_urls: list[tuple[str, int]]  # (url, weight)
    min_tvl_usd: float


def _load_chains_yaml() -> dict[str, Any]:
    return yaml.safe_load((CONFIG_DIR / "chains.yaml").read_text())


def _load_pool_seeds() -> dict[str, list[dict[str, Any]]]:
    return json.loads((CONFIG_DIR / "pool_seeds.json").read_text())


@lru_cache(maxsize=1)
def get_chains() -> dict[str, ChainConfig]:
    raw = _load_chains_yaml()["chains"]
    out: dict[str, ChainConfig] = {}
    for name, spec in raw.items():
        out[name] = ChainConfig(
            name=name,
            chain_id=int(spec["chain_id"]),
            multicall3=spec["multicall3"],
            rpc_urls=[(u["url"], int(u.get("weight", 1))) for u in spec["rpc_urls"]],
            min_tvl_usd=float(spec.get("min_tvl_usd", 0)),
        )
    return out


@lru_cache(maxsize=1)
def get_pool_seeds() -> dict[str, list[dict[str, Any]]]:
    return _load_pool_seeds()


def get_chain(name: str) -> ChainConfig:
    cfg = get_chains().get(name.lower())
    if cfg is None:
        raise KeyError(f"Unknown chain: {name}. Known: {list(get_chains())}")
    return cfg
