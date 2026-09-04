"""Multicall3 batch aggregator.

Packs arbitrary ``(target, calldata)`` reads into ``aggregate3`` calls with
``requireSuccess=False`` so a single reverting sub-call doesn't poison the
batch. Calls are chunked at ``chunk_size`` (default 100) to stay under public
RPC payload-size limits; multiple chunks run concurrently.

Decoding returns a flat ``list[tuple[bool, bytes]]`` aligned with the input
calldata order. Adapters interpret their slice.

The batcher never touches transport — it gets a ``ResilientRPCManager``
injected and issues a single ``eth_call`` to the chain's Multicall3 address
per chunk.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import structlog
from eth_abi import decode as decode_abi
from eth_abi import encode as encode_abi
from eth_utils import to_checksum_address
from whaledecode.pools.config.loader import DEFAULT_MULTICALL_CHUNK, get_chain

log = structlog.get_logger()

# aggregate3((address,bool,bytes)[]) — selector identical on all chains.
# The return type is ``(bool,bytes)[]`` (Result[] in the contract ABI).
AGGREGATE3_SELECTOR = bytes.fromhex("82ad56cb")
MULTICALL3_INPUT_TYPE = "(address,bool,bytes)[]"
MULTICALL3_OUTPUT_TYPE = "(bool,bytes)[]"


@dataclass(frozen=True)
class MulticallSpec:
    """A single sub-call to pack into the batch.

    ``target`` is the checksummed EVM address (0x-prefixed). ``calldata`` is
    the function-selector-prefixed payload (selector + ABI-encoded args).
    """

    target: str
    calldata: bytes
    tag: str = ""


class MulticallBatcher:
    """Owns one Multicall3 invocation path per chain.

    ponytail: pure stateless aggregator — no caching, no retry. The
    ``ResilientRPCManager`` owns failover and breakers; the batcher just packs
    and decodes. add when per-pool state caching becomes a thing.
    """

    def __init__(
        self,
        rpc: Any,
        chunk_size: int = DEFAULT_MULTICALL_CHUNK,
    ) -> None:
        self._rpc = rpc
        self._chunk_size = max(1, int(chunk_size))

    async def aggregate3(
        self,
        chain: str,
        specs: list[MulticallSpec],
    ) -> list[tuple[bool, bytes]]:
        """Send ``specs`` to ``chain``'s Multicall3, return per-spec ``(ok, ret)``."""
        if not specs:
            return []
        get_chain(chain)
        chunks = [specs[i : i + self._chunk_size] for i in range(0, len(specs), self._chunk_size)]
        if len(chunks) == 1:
            rows = await self._run_chunk(chain, chunks[0])
            return list(rows)
        results_lists = await asyncio.gather(*(self._run_chunk(chain, c) for c in chunks))
        flat: list[tuple[bool, bytes]] = []
        for sub in results_lists:
            flat.extend(sub)
        return flat

    async def _run_chunk(self, chain: str, specs: list[MulticallSpec]) -> list[tuple[bool, bytes]]:
        cfg = get_chain(chain)
        payload_bytes = self._build_payload(specs)
        raw_hex = await self._rpc.execute(
            chain,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_call",
                "params": [
                    {"to": cfg.multicall3, "data": "0x" + payload_bytes.hex()},
                    "latest",
                ],
            },
        )
        if not isinstance(raw_hex, str) or not raw_hex.startswith("0x"):
            raise ValueError(f"{chain}: Multicall3 returned non-bytes: {raw_hex!r}")
        return self._decode_payload(raw_hex, len(specs))

    def _build_payload(self, specs: list[MulticallSpec]) -> bytes:
        # requireSuccess=False so a single reverting sub-call comes back as
        # (success=false, ret=0x) instead of poisoning the whole batch.
        packed = [(to_checksum_address(spec.target), False, spec.calldata) for spec in specs]
        return AGGREGATE3_SELECTOR + encode_abi([MULTICALL3_INPUT_TYPE], [packed])

    def _decode_payload(self, raw_hex: str, expected: int) -> list[tuple[bool, bytes]]:
        body = bytes.fromhex(raw_hex[2:])
        decoded = decode_abi([MULTICALL3_OUTPUT_TYPE], body)
        rows = decoded[0] if (len(decoded) == 1 and isinstance(decoded[0], list | tuple)) else decoded
        out: list[tuple[bool, bytes]] = []
        for success, retdata in rows:
            out.append((bool(success), bytes(retdata)))
        while len(out) < expected:
            out.append((False, b""))
        return out[:expected]


__all__ = ["MulticallBatcher", "MulticallSpec", "AGGREGATE3_SELECTOR"]
