"""Pool-system RPC plumbing.

``ResilientRPCManager`` wraps the existing ``RpcFailoverRouter`` with chain-level
circuit breakers and a transparent retry decorator. ``MulticallBatcher`` packs
arbitrary reads into Multicall3 ``aggregate3`` calls with per-call failure
isolation.
"""
from whaledecode.pools.rpc.manager import (
    DEFAULT_BREAKER_THRESHOLD,
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    CircuitOpenError,
    ResilientRPCManager,
)
from whaledecode.pools.rpc.multicall import (
    AGGREGATE3_SELECTOR,
    MulticallBatcher,
    MulticallSpec,
)

__all__ = [
    "AGGREGATE3_SELECTOR",
    "CircuitOpenError",
    "DEFAULT_BREAKER_THRESHOLD",
    "DEFAULT_COOLDOWN_SECONDS",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_TIMEOUT",
    "MulticallBatcher",
    "MulticallSpec",
    "ResilientRPCManager",
]
