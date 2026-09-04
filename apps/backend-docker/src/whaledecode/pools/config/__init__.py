"""Pool-system chain + seed configs.

``chains.yaml`` (RPC endpoints, Multicall3 addresses, min-TVL thresholds) and
``pool_seeds.json`` (canonical verified pools) live here. ``loader`` parses
them with caching.
"""
from whaledecode.pools.config.loader import (
    DEFAULT_MULTICALL_CHUNK,
    ChainConfig,
    get_chain,
    get_chains,
    get_pool_seeds,
)

__all__ = [
    "DEFAULT_MULTICALL_CHUNK",
    "ChainConfig",
    "get_chain",
    "get_chains",
    "get_pool_seeds",
]
