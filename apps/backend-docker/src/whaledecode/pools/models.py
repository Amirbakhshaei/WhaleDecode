"""Models for the pool registry: Token, Pool, PoolState.

All accounting is integer wei. No floats. Address fields are stored checksummed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DexKind(str, Enum):
    UNISWAP_V2 = "uniswap_v2"
    UNISWAP_V3 = "uniswap_v3"
    AERODROME = "aerodrome"
    SLIPSTREAM = "slipstream"


@dataclass(frozen=True)
class Token:
    """Immutable ERC-20 token descriptor. ``address`` is always checksummed."""

    address: str
    symbol: str
    decimals: int

    def to_topic(self) -> str:
        """32-byte left-padded hex topic (used in Multicall3 calldata)."""
        return self.address.lower().removeprefix("0x").rjust(64, "0")


@dataclass(frozen=True)
class Pool:
    """A verified pool. ``address`` is checksummed.

    ``dex`` selects the adapter that knows how to decode ``slot0`` / ``getReserves``
    / ``liquidity`` for this pool family.
    """

    address: str
    chain_id: int
    dex: DexKind
    token0: Token
    token1: Token
    fee_tier: int = 0
    block_number: int = 0  # block at which we last refreshed state

    @property
    def key(self) -> tuple[int, str]:
        return (self.chain_id, self.address.lower())


@dataclass
class PoolState:
    """Live state snapshot. ``reserve0`` / ``reserve1`` are raw wei.

    ``tick`` / ``sqrt_price_x96`` are populated for V3/Slipstream; ``reserve0/1``
    for V2. ``None`` means "this field is not defined for the pool's DEX family",
    not "we forgot to populate it".
    """

    pool_address: str
    chain_id: int
    reserve0: int | None = None
    reserve1: int | None = None
    sqrt_price_x96: int | None = None
    tick: int | None = None
    liquidity: int | None = None
    block_number: int = 0
    extras: dict[str, Any] = field(default_factory=dict)

    def is_alive(self) -> bool:
        """Has at least one non-zero, non-None reserve/liquidity field."""
        if self.reserve0 is not None and self.reserve0 > 0:
            return True
        if self.reserve1 is not None and self.reserve1 > 0:
            return True
        if self.liquidity is not None and self.liquidity > 0:
            return True
        return False
