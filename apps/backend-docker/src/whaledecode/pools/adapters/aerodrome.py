"""Aerodrome (Base) adapter — handles both Classic (Solidly-style) and Slipstream.

* **Classic pools** expose the same ``getReserves()`` ABI as Uniswap V2, but
  Aerodrome also stores the ``emissions`` (per-token reward rate) on a separate
  field we don't read here. We probe `slot0` first; if it reverts we treat the
  pool as Classic and only call `getReserves`.

* **Slipstream pools** (concentrated liquidity on Base) deploy the standard
  Uniswap V3 ``slot0()`` / ``liquidity()`` interface, so we reuse the V3
  selectors.

Branching inside one adapter keeps the registry's dispatcher (`Pool.dex`)
simple — both pool kinds register as ``DexKind.AERODROME``.
"""
from __future__ import annotations

from eth_abi import decode as decode_abi
from whaledecode.pools.adapters.base import DexAdapter
from whaledecode.pools.adapters.uniswap_v3 import (
    LIQUIDITY_SELECTOR,
    SLOT0_HEAD_TYPES,
    SLOT0_SELECTOR,
)
from whaledecode.pools.models import DexKind, Pool, PoolState

GETRESERVES_SELECTOR = b"\x09\x05\x2e\xD9\x65"
_GETRESERVES_TYPES = ["uint112", "uint112", "uint32"]


class AerodromeAdapter(DexAdapter):
    dex = DexKind.AERODROME

    def encode_state_calls(self, pool: Pool) -> list[tuple[bytes, bytes]]:
        """Always issue slot0 + liquidity + getReserves; the decoder skips the
        ones that revert. Per-call ``requireSuccess=False`` on the Multicall3
        batch makes this cheap (one RPC round-trip regardless).
        """
        target = bytes.fromhex(self.verify_address(pool.address).removeprefix("0x"))
        return [
            (target, SLOT0_SELECTOR),
            (target, LIQUIDITY_SELECTOR),
            (target, GETRESERVES_SELECTOR),
        ]

    def decode_state(
        self,
        pool: Pool,
        raw_returns: list[tuple[bool, bytes]],
        block_number: int,
    ) -> PoolState:
        state = PoolState(pool_address=pool.address, chain_id=pool.chain_id, block_number=block_number)
        # Slipstream path: slot0 + liquidity both succeed.
        if len(raw_returns) >= 2 and raw_returns[0][0] and raw_returns[1][0]:
            ok0, ret0 = raw_returns[0]
            ok1, ret1 = raw_returns[1]
            if len(ret0) >= 64:
                sqrt_price_x96, tick = decode_abi(SLOT0_HEAD_TYPES, ret0[:64])
                state.sqrt_price_x96 = int(sqrt_price_x96)
                state.tick = int(tick)
            if len(ret1) >= 32:
                state.liquidity = int.from_bytes(ret1[:32], "big")
            return state
        # Classic path: getReserves succeeds; slot0/liquidity revert.
        if len(raw_returns) >= 3 and raw_returns[2][0]:
            _, ret = raw_returns[2]
            if len(ret) >= 96:
                r0, r1, _ts = decode_abi(_GETRESERVES_TYPES, ret)
                state.reserve0 = int(r0)
                state.reserve1 = int(r1)
        return state
