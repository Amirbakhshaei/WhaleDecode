"""DEX adapter dispatch by ``Pool.dex``.

Adding a new DEX = one new module + one entry here. Registry uses
``ADAPTERS`` to look up the right adapter for a pool.
"""
from whaledecode.pools.adapters.aerodrome import AerodromeAdapter
from whaledecode.pools.adapters.base import DexAdapter
from whaledecode.pools.adapters.uniswap_v2 import UniswapV2Adapter
from whaledecode.pools.adapters.uniswap_v3 import UniswapV3Adapter
from whaledecode.pools.models import DexKind

ADAPTERS: dict[DexKind, DexAdapter] = {
    DexKind.UNISWAP_V2: UniswapV2Adapter(),
    DexKind.UNISWAP_V3: UniswapV3Adapter(),
    DexKind.AERODROME: AerodromeAdapter(),
    DexKind.SLIPSTREAM: UniswapV3Adapter(),  # Slipstream inherits V3's ABI
}


def get_adapter(dex: DexKind) -> DexAdapter:
    adapter = ADAPTERS.get(dex)
    if adapter is None:
        raise KeyError(f"No adapter registered for dex={dex}")
    return adapter


__all__ = ["ADAPTERS", "DexAdapter", "get_adapter"]
