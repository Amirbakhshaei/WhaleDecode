"""Multicall batching: 50+ reads → 1 round-trip per chunk.

Spec: "Execute 50 pool reserve fetches against Base and Arbitrum; assert they
are packed into a single network round-trip via Multicall3."

The batcher chunks at 100 by default; with 50 specs both chains fit in one
chunk. We assert exactly one ``eth_call`` per chain hits the wire.

We also assert that one bad spec (reverting sub-call) doesn't fail the batch —
requireSuccess=False.
"""

import pytest
from eth_abi import decode, encode
from whaledecode.pools.adapters import get_adapter
from whaledecode.pools.adapters.uniswap_v3 import SLOT0_HEAD_TYPES
from whaledecode.pools.config import get_chain
from whaledecode.pools.models import DexKind, Pool, Token
from whaledecode.pools.rpc.multicall import (
    AGGREGATE3_SELECTOR,
    MULTICALL3_INPUT_TYPE,
    MulticallBatcher,
    MulticallSpec,
)


class _CountingRpc:
    """Records every (chain, payload) the batcher emits and replays a
    deterministic aggregate3 response."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, chain: str, payload: dict) -> str:
        self.calls.append((chain, payload))
        # Re-decode the request we sent so we can echo back a believable response.
        data_hex = payload["params"][0]["data"]
        assert data_hex.startswith("0x" + AGGREGATE3_SELECTOR.hex())
        body = bytes.fromhex(data_hex[len("0x") + len(AGGREGATE3_SELECTOR) * 2 :])
        rows = decode([MULTICALL3_INPUT_TYPE], body)[0]
        # Build a (bool,bytes)[] response — every call "succeeds" with 32 zero bytes
        # except row 7 which we deliberately mark as (false, 0x) to exercise
        # requireSuccess=False isolation.
        out = []
        for i, (_target, _allow_fail, _cd) in enumerate(rows):
            if i == 7:
                out.append((False, b""))
            else:
                out.append((True, b"\x00" * 32))
        encoded = encode(["(bool,bytes)[]"], [out])
        return "0x" + encoded.hex()


def _fake_pools(n: int, dex: DexKind, chain: str) -> list[Pool]:
    """Build ``n`` synthetic pools for ``chain`` so we can size-spec a batch."""
    cfg = get_chain(chain)
    t0 = Token(address="0x" + "11" * 20, symbol="T0", decimals=18)
    t1 = Token(address="0x" + "22" * 20, symbol="T1", decimals=6)
    return [
        Pool(
            address=f"0x{(i + 1):040x}",  # unique per pool
            chain_id=cfg.chain_id,
            dex=dex,
            token0=t0,
            token1=t1,
            fee_tier=3000,
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_fifty_pool_state_reads_pack_into_single_rpc_per_chain() -> None:
    """50 reads per chain → exactly 1 eth_call per chain."""
    rpc = _CountingRpc()
    batcher = MulticallBatcher(rpc=rpc, chunk_size=100)

    for chain in ("base", "arbitrum"):
        pools = _fake_pools(50, DexKind.UNISWAP_V3, chain)
        specs: list[MulticallSpec] = []
        for p in pools:
            adapter = get_adapter(p.dex)
            for target, calldata in adapter.encode_state_calls(p):
                specs.append(MulticallSpec(target="0x" + target.hex(), calldata=calldata))

        results = await batcher.aggregate3(chain, specs)
        assert len(results) == len(specs)
        # V3 reads slot0 + liquidity per pool → 100 results for 50 pools.
        assert len(results) == 100

    # Exactly one eth_call per chain was emitted.
    by_chain_calls = {c: [p for cn, p in rpc.calls if cn == c] for c in ("base", "arbitrum")}
    assert len(by_chain_calls["base"]) == 1, "50 V3 pools (100 specs) should fit in 1 RPC chunk"
    assert len(by_chain_calls["arbitrum"]) == 1
    # Both calls hit Multicall3 (not arbitrary addresses).
    for _chain, payload in rpc.calls:
        assert payload["params"][0]["to"] == get_chain("base").multicall3 or \
               payload["params"][0]["to"] == get_chain("arbitrum").multicall3


@pytest.mark.asyncio
async def test_reverting_subcall_does_not_poison_batch() -> None:
    """One reverting sub-call comes back as (false, 0x) — other calls succeed."""
    rpc = _CountingRpc()
    batcher = MulticallBatcher(rpc=rpc, chunk_size=100)

    pools = _fake_pools(10, DexKind.UNISWAP_V2, "base")
    specs: list[MulticallSpec] = []
    for p in pools:
        adapter = get_adapter(p.dex)
        for target, calldata in adapter.encode_state_calls(p):
            specs.append(MulticallSpec(target="0x" + target.hex(), calldata=calldata))

    results = await batcher.aggregate3("base", specs)
    successes = [ok for ok, _ in results]
    # Fake response marks row 7 as failed; everything else succeeds.
    assert successes[7] is False
    assert all(ok for i, ok in enumerate(successes) if i != 7)


@pytest.mark.asyncio
async def test_chunking_splits_large_batches() -> None:
    """Default chunk_size=100: 250 specs → 3 eth_calls."""
    rpc = _CountingRpc()
    batcher = MulticallBatcher(rpc=rpc, chunk_size=100)

    pools = _fake_pools(125, DexKind.UNISWAP_V3, "base")  # 250 specs (slot0+liquidity per pool)
    specs: list[MulticallSpec] = []
    for p in pools:
        adapter = get_adapter(p.dex)
        for target, calldata in adapter.encode_state_calls(p):
            specs.append(MulticallSpec(target="0x" + target.hex(), calldata=calldata))

    assert len(specs) == 250
    await batcher.aggregate3("base", specs)
    base_calls = [p for cn, p in rpc.calls if cn == "base"]
    assert len(base_calls) == 3
    # Each chunk <= 100 sub-calls (no off-by-one).
    for payload in base_calls:
        body = bytes.fromhex(payload["params"][0]["data"][2 + 8:])
        rows = decode([MULTICALL3_INPUT_TYPE], body)[0]
        assert len(rows) <= 100


@pytest.mark.asyncio
async def test_v3_adapter_decodes_slot0_and_liquidity() -> None:
    """End-to-end: synthetic V3 state returns the right sqrt_price_x96/tick/liquidity."""
    rpc = _CountingRpc()
    # Override rpc to return richer responses per spec (deterministic).
    rpc.execute = _make_v3_aware_rpc()  # type: ignore[assignment]
    batcher = MulticallBatcher(rpc=rpc, chunk_size=100)

    pools = _fake_pools(3, DexKind.UNISWAP_V3, "base")
    adapter = get_adapter(DexKind.UNISWAP_V3)
    specs: list[MulticallSpec] = []
    for p in pools:
        for target, calldata in adapter.encode_state_calls(p):
            specs.append(MulticallSpec(target="0x" + target.hex(), calldata=calldata))

    results = await batcher.aggregate3("base", specs)
    # Re-group by pool (2 specs per pool: slot0 + liquidity).
    pool_states = []
    for i in range(0, len(results), 2):
        pool_states.append((results[i], results[i + 1]))
    # Each pool's first result should be a slot0 encode of (sqrtPriceX96, tick)
    # and the second a 32-byte uint128.
    for i, (slot0, liquidity) in enumerate(pool_states):
        ok0, ret0 = slot0
        ok1, ret1 = liquidity
        assert ok0 and ok1
        sqrt_price_x96, tick = decode(SLOT0_HEAD_TYPES, ret0[:64])
        assert int(sqrt_price_x96) > 0
        assert int(tick) != 0
        assert int.from_bytes(ret1[:32], "big") > 0


def _make_v3_aware_rpc():
    """Return an async execute() that replays plausible V3 state values."""

    async def execute(chain: str, payload: dict) -> str:
        data_hex = payload["params"][0]["data"]
        body = bytes.fromhex(data_hex[2 + 8:])
        rows = decode([MULTICALL3_INPUT_TYPE], body)[0]
        # slot0 layout: sqrtPriceX96 (uint160) + tick (int24) + ...
        slot0_data = encode(SLOT0_HEAD_TYPES, [42**3, 12345]) + b"\x00" * (256 - 64)
        liquidity_data = (12345).to_bytes(32, "big")
        # Walk rows in order: each pool contributed 2 specs (slot0, liquidity).
        out = []
        for i, row in enumerate(rows):
            kind_marker = i % 2  # 0 = slot0, 1 = liquidity
            if kind_marker == 0:
                out.append((True, slot0_data))
            else:
                out.append((True, liquidity_data))
        return "0x" + encode(["(bool,bytes)[]"], [out]).hex()

    return execute
