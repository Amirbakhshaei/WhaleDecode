"""Uniswap V3 adapter — ``slot0()`` + ``liquidity()`` packed in one batch.

``slot0()`` returns ``(uint160 sqrtPriceX96, int24 tick, uint16 observationIndex,
uint16 observationCardinality, uint16 observationCardinalityNext, uint8 feeProtocol,
bool unlocked)``. We need only the first two.

``liquidity()`` returns the current in-range liquidity as ``uint128``.

Both selectors packed into a single Multicall3 ``aggregate3`` call = 1 RPC.
"""
from __future__ import annotations

from eth_abi import decode as decode_abi
from whaledecode.pools.adapters.base import DexAdapter
from whaledecode.pools.models import DexKind, Pool, PoolState

SLOT0_SELECTOR = b"\x38\x50\x7a\x1A"  # keccak256("slot0()")[:4]
LIQUIDITY_SELECTOR = b"\x1a\x68\x58\x1F"  # keccak256("liquidity()")[:4]

# We only consume the first two words of slot0 (sqrtPriceX96, tick).
SLOT0_HEAD_TYPES = ["uint160", "int24"]


class UniswapV3Adapter(DexAdapter):
    dex = DexKind.UNISWAP_V3

    def encode_state_calls(self, pool: Pool) -> list[tuple[bytes, bytes]]:
        target = bytes.fromhex(self.verify_address(pool.address).removeprefix("0x"))
        return [
            (target, SLOT0_SELECTOR),
            (target, LIQUIDITY_SELECTOR),
        ]

    def decode_state(
        self,
        pool: Pool,
        raw_returns: list[tuple[bool, bytes]],
        block_number: int,
    ) -> PoolState:
        state = PoolState(pool_address=pool.address, chain_id=pool.chain_id, block_number=block_number)
        if len(raw_returns) < 2:
            return state
        ok0, ret0 = raw_returns[0]
        ok1, ret1 = raw_returns[1]
        if ok0 and len(ret0) >= 64:
            sqrt_price_x96, tick = decode_abi(SLOT0_HEAD_TYPES, ret0[:64])
            state.sqrt_price_x96 = int(sqrt_price_x96)
            state.tick = int(tick)
        if ok1 and len(ret1) >= 32:
            state.liquidity = int.from_bytes(ret1[:32], "big")
        return state
