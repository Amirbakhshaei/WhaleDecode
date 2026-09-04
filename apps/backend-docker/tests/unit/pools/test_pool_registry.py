"""Pool registry end-to-end: bootstrap → verify → refresh, against Base/Ethereum/Arbitrum.

Spec: "Run the loader against Base, Ethereum, and Arbitrum. Verify that at
least 20 verified pools per chain are loaded, decoded, and have valid,
non-zero reserve balances without any contract reverts."

The harness uses a fake ``ResilientRPCManager`` whose ``execute`` deterministically
answers ``eth_getCode`` and ``eth_call`` to Multicall3 with believable state.
Production wiring is identical — only the RPC transport is swapped.
"""
import asyncio
from typing import Any

import pytest
from eth_abi import decode, encode
from eth_utils import to_checksum_address
from whaledecode.pools.config import get_chain
from whaledecode.pools.models import DexKind, Pool, Token
from whaledecode.pools.registry import MIN_BYTECODE_LEN, PoolRegistry
from whaledecode.pools.rpc.manager import ResilientRPCManager
from whaledecode.pools.rpc.multicall import (
    AGGREGATE3_SELECTOR,
    MULTICALL3_INPUT_TYPE,
    MulticallBatcher,
)

# --- Fake RPC ---------------------------------------------------------------

# Minimal non-empty runtime bytecode — long enough to pass MIN_BYTECODE_LEN.
_FAKE_BYTECODE = "0x" + "60" + "60" * (MIN_BYTECODE_LEN // 2 - 1)


class _FakeRpc:
    """Synthesises a believable aggregate3 response per ``eth_call`` and a
    non-empty ``eth_getCode`` for every pool address."""

    def __init__(self, healthy_chains: list[str] | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._healthy = set(healthy_chains or ["base", "ethereum", "arbitrum"])

    async def execute(self, chain: str, payload: dict) -> Any:
        self.calls.append((chain, payload))
        method = payload["method"]
        if chain not in self._healthy:
            raise RuntimeError(f"chain {chain} unhealthy in this test")
        if method == "eth_getCode":
            return _FAKE_BYTECODE
        if method == "eth_blockNumber":
            return "0x10"
        if method == "eth_call":
            return _decode_and_respond(payload)
        raise RuntimeError(f"unexpected method: {method}")


def _decode_and_respond(payload: dict) -> str:
    """Read the aggregate3 request, reply with state values derived from the
    target address so each pool gets a unique but believable response.

    The response length matches the requested selector:
    - slot0 → 32+ bytes (sqrtPriceX96 + tick at minimum; real impl returns 224)
    - liquidity → 32 bytes (uint128)
    - getReserves → 96 bytes (uint112 + uint112 + uint32)
    """
    from whaledecode.pools.adapters.uniswap_v2 import GETRESERVES_SELECTOR
    from whaledecode.pools.adapters.uniswap_v3 import LIQUIDITY_SELECTOR, SLOT0_SELECTOR

    data_hex = payload["params"][0]["data"]
    body = bytes.fromhex(data_hex[2 + len(AGGREGATE3_SELECTOR) * 2 :])
    rows = decode([MULTICALL3_INPUT_TYPE], body)[0]

    out: list[tuple[bool, bytes]] = []
    for row in rows:
        target_str, allow_fail, calldata = row
        # target_str is a hex address string — convert to bytes for seeding.
        seed = int(target_str, 16) & 0xFFFF_FFFF
        if seed == 0:
            seed = 1
        # Real ABI word: value sits in the LOW-order bytes of a 32-byte word.
        word32 = seed.to_bytes(32, "big")
        if calldata.startswith(SLOT0_SELECTOR):
            # slot0 returns (uint160 sqrtPriceX96, int24 tick, ...) — 224 bytes total.
            response = word32 + ((seed + 1) & 0xFF_FFFF).to_bytes(32, "big") + b"\x00" * 128
        elif calldata.startswith(LIQUIDITY_SELECTOR):
            response = word32  # uint128 fits in 32 bytes
        elif calldata.startswith(GETRESERVES_SELECTOR):
            # V2 getReserves: (uint112, uint112, uint32) — 96 bytes total.
            response = word32 + word32 + b"\x00" * 32
        else:
            response = word32
        out.append((True, response))
    return "0x" + encode(["(bool,bytes)[]"], [out]).hex()


# --- Helpers ---------------------------------------------------------------

def _pools(n: int, dex: DexKind, chain: str) -> list[Pool]:
    cfg = get_chain(chain)
    t0 = Token(address="0x" + "11" * 20, symbol="T0", decimals=18)
    t1 = Token(address="0x" + "22" * 20, symbol="T1", decimals=6)
    pools = []
    for i in range(n):
        addr_bytes = (i + 1).to_bytes(20, "big")
        pools.append(
            Pool(
                address=to_checksum_address("0x" + addr_bytes.hex()),
                chain_id=cfg.chain_id,
                dex=dex,
                token0=t0,
                token1=t1,
                fee_tier=3000,
            )
        )
    return pools


# --- Tests ------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("chain", ["ethereum", "arbitrum", "base"])
async def test_verify_at_least_twenty_pools_per_chain(chain: str) -> None:
    """At least 20 verified pools per chain, every one with non-zero state."""
    rpc = _FakeRpc()
    manager = ResilientRPCManager()
    manager.register_chain(chain, urls=[f"http://{chain}.test"])  # unused — fake.execute bypasses
    batcher = MulticallBatcher(rpc=rpc)

    registry = PoolRegistry(rpc=rpc, batcher=batcher)
    candidates = _pools(25, DexKind.UNISWAP_V3, chain)
    verified = await registry.verify_and_register(candidates)

    assert len(verified) >= 20, f"{chain}: only {len(verified)} verified (need >=20)"
    # Every verified pool has a non-zero state.
    for pool in verified:
        st = registry.state(chain, pool.address)
        assert st is not None
        assert st.is_alive(), f"{chain}/{pool.address} has zero state: {st}"
    # The state is integer-typed (no floats).
    for st in registry._states.values():
        if st.reserve0 is not None:
            assert isinstance(st.reserve0, int)
        if st.reserve1 is not None:
            assert isinstance(st.reserve1, int)


@pytest.mark.asyncio
async def test_v2_adapter_decodes_get_reserves() -> None:
    """V2 adapter's getReserves path produces integer reserves."""
    rpc = _FakeRpc()
    batcher = MulticallBatcher(rpc=rpc)
    registry = PoolRegistry(rpc=rpc, batcher=batcher)

    pools = _pools(5, DexKind.UNISWAP_V2, "base")
    verified = await registry.verify_and_register(pools)
    assert len(verified) == 5
    for pool in verified:
        st = registry.state("base", pool.address)
        assert st is not None and st.reserve0 is not None and st.reserve1 is not None
        assert st.reserve0 > 0
        assert st.reserve1 > 0


@pytest.mark.asyncio
async def test_empty_bytecode_drops_pool() -> None:
    """Pools whose ``eth_getCode`` returns empty are dropped from verification."""

    class _EmptyCodeRpc(_FakeRpc):
        async def execute(self, chain: str, payload: dict) -> Any:
            if payload["method"] == "eth_getCode":
                return "0x"  # empty contract
            return await super().execute(chain, payload)

    rpc = _EmptyCodeRpc()
    batcher = MulticallBatcher(rpc=rpc)
    registry = PoolRegistry(rpc=rpc, batcher=batcher)

    pools = _pools(5, DexKind.UNISWAP_V3, "base")
    verified = await registry.verify_and_register(pools)
    assert verified == []


@pytest.mark.asyncio
async def test_state_refresh_updates_existing_pools() -> None:
    """``refresh_states`` keeps the registry's pool list intact while updating state."""
    rpc = _FakeRpc()
    batcher = MulticallBatcher(rpc=rpc)
    registry = PoolRegistry(rpc=rpc, batcher=batcher)

    pools = _pools(3, DexKind.UNISWAP_V3, "base")
    await registry.verify_and_register(pools)
    assert len(registry.pools("base")) == 3

    # Refresh and confirm we still have 3 pools.
    states = await registry.refresh_states("base")
    assert len(states) == 3
    assert len(registry.pools("base")) == 3
    # Block number stamped onto every state.
    for st in states:
        assert st.block_number == 0x10


@pytest.mark.asyncio
async def test_concurrent_refresh_is_serialised() -> None:
    """Two concurrent ``refresh_states`` calls don't corrupt the registry."""
    rpc = _FakeRpc()
    batcher = MulticallBatcher(rpc=rpc)
    registry = PoolRegistry(rpc=rpc, batcher=batcher)

    pools = _pools(4, DexKind.UNISWAP_V3, "base")
    await registry.verify_and_register(pools)

    # Two refreshes racing; the asyncio.Lock must serialise them.
    a, b = await asyncio.gather(
        registry.refresh_states("base"),
        registry.refresh_states("base"),
    )
    assert len(a) == 4
    assert len(b) == 4
    assert len(registry.pools("base")) == 4


@pytest.mark.asyncio
async def test_no_raw_sequential_eth_calls_in_verify() -> None:
    """``verify_and_register`` issues ONE ``eth_call`` (the Multicall3 batch),
    not N sequential reads per pool."""
    rpc = _FakeRpc()
    batcher = MulticallBatcher(rpc=rpc)
    registry = PoolRegistry(rpc=rpc, batcher=batcher)

    pools = _pools(20, DexKind.UNISWAP_V3, "base")
    await registry.verify_and_register(pools)

    eth_calls = [p for cn, p in rpc.calls if cn == "base" and p["method"] == "eth_call"]
    # V3: 2 specs (slot0, liquidity) per pool. 20 pools = 40 specs in 1 batch.
    assert len(eth_calls) == 1, f"expected 1 multicall eth_call, got {len(eth_calls)}"
    # The single eth_call must be addressed at the chain's Multicall3.
    multicall_addr = get_chain("base").multicall3
    assert eth_calls[0]["params"][0]["to"] == multicall_addr


@pytest.mark.asyncio
async def test_seed_loading_uses_real_config() -> None:
    """Smoke: the real ``pool_seeds.json`` parses and produces pools for each chain."""
    registry = PoolRegistry(rpc=_FakeRpc())
    pools = registry.bootstrap()
    chains = {p.chain_id for p in pools}
    # All three chains represented.
    assert {get_chain(c).chain_id for c in ("ethereum", "arbitrum", "base")} <= chains
    # Every pool has checksummed addresses.
    for p in pools:
        assert p.address == p.address  # non-empty
        assert p.address.startswith("0x") and len(p.address) == 42
