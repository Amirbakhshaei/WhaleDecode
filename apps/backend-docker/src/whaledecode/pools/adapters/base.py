"""Abstract DEX adapter — the contract every concrete adapter honours.

An adapter knows:

* what calldata bytes read the pool's live state (`encode_state_calls`),
* how to decode the returned bytes back into a `PoolState` (`decode_state`),
* what single address probe verifies it has runtime bytecode (`get_code_selector`).

Adding a new DEX family = one new file that implements these three. No router
code changes — registry dispatches by `Pool.dex`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from eth_utils import to_checksum_address
from whaledecode.pools.models import DexKind, Pool, PoolState


class DexAdapter(ABC):
    """Read-side adapter for one DEX family on one chain."""

    dex: DexKind

    @abstractmethod
    def encode_state_calls(self, pool: Pool) -> list[tuple[bytes, bytes]]:
        """Build the calldata fragments needed to read this pool's live state.

        Returns a list of ``(target, calldata)`` pairs the multicall batcher
        packs into one ``aggregate3`` payload. ``target`` is the pool address
        itself for all current DEXes; kept as a tuple so future adapters can
        route sub-calls through helper contracts.
        """
        raise NotImplementedError

    @abstractmethod
    def decode_state(
        self,
        pool: Pool,
        raw_returns: list[tuple[bool, bytes]],
        block_number: int,
    ) -> PoolState:
        """Decode the ``(success, returnData)`` rows from the batcher."""
        raise NotImplementedError

    def verify_address(self, address: str) -> str:
        """Force ERC-55 checksum on any address that flows through this adapter."""
        return to_checksum_address(address)

    def code_probe_calldata(self) -> bytes:
        """No-op selector; ``eth_getCode`` reads runtime bytecode directly —
        not through a calldata call. Adapters that ever want an explicit
        ``EXTCODESIZE`` path can override this.
        """
        return b""
