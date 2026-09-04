"""Uniswap V2 adapter — ``getReserves()`` returns ``(uint112, uint112, uint32)``."""
from __future__ import annotations

from eth_abi import decode as decode_abi
from whaledecode.pools.adapters.base import DexAdapter
from whaledecode.pools.models import DexKind, Pool, PoolState

# getReserves() selector
GETRESERVES_SELECTOR = b"\x09\x05\x2e\xD9\x65"  # keccak256("getReserves()")[:4]

# V2 stores reserves in uint112 fields inside a 3-word struct; the trailing
# uint32 is the block timestamp of last change (we ignore it).
_GETRESERVES_TYPES = ["uint112", "uint112", "uint32"]


class UniswapV2Adapter(DexAdapter):
    dex = DexKind.UNISWAP_V2

    def encode_state_calls(self, pool: Pool) -> list[tuple[bytes, bytes]]:
        addr = self.verify_address(pool.address)
        return [(bytes.fromhex(addr.removeprefix("0x")), GETRESERVES_SELECTOR)]

    def decode_state(
        self,
        pool: Pool,
        raw_returns: list[tuple[bool, bytes]],
        block_number: int,
    ) -> PoolState:
        if not raw_returns or not raw_returns[0][0]:
            return PoolState(
                pool_address=pool.address,
                chain_id=pool.chain_id,
                block_number=block_number,
            )
        success, ret = raw_returns[0]
        if len(ret) < 96:
            return PoolState(pool_address=pool.address, chain_id=pool.chain_id, block_number=block_number)
        r0, r1, _ts = decode_abi(_GETRESERVES_TYPES, ret)
        return PoolState(
            pool_address=pool.address,
            chain_id=pool.chain_id,
            reserve0=int(r0),
            reserve1=int(r1),
            block_number=block_number,
        )
