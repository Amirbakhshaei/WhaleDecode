"""Pool & DEX plumbing for high-liquidity pools across EVM chains.

Public surface intentionally small: the pool dataclasses, the adapter
dispatch, and the registry. RPC plumbing is reachable through
``whaledecode.pools.rpc`` for callers that want it directly.
"""
from whaledecode.pools.adapters import DexAdapter, get_adapter
from whaledecode.pools.models import DexKind, Pool, PoolState, Token
from whaledecode.pools.registry import PoolRegistry

__all__ = [
    "DexAdapter",
    "DexKind",
    "Pool",
    "PoolRegistry",
    "PoolState",
    "Token",
    "get_adapter",
]
