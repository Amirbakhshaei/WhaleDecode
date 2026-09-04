"""Pool registry: bootstrap → on-chain verify → refresh → serve.

Lifecycle:

1. ``load_from_seeds()`` reads ``pool_seeds.json`` (canonical pools per chain).
2. ``verify_with_multicall()`` issues ONE Multicall3 batch that simultaneously:
    - reads ``eth_getCode`` (already batched at the registry level via a
      pseudo-call) for each candidate pool,
    - runs the pool's adapter state calls (slot0, liquidity, getReserves).
   Pools whose contract is empty or whose state-call reverts are dropped.
3. Verified pools land in ``self._pools`` keyed by ``(chain_id, address)``.
4. ``refresh_states()`` re-issues the adapter batch against every verified
   pool on every confirmed new block, populating ``self._states``.

Concurrency: ``self._pools`` / ``self._states`` are protected by an
``asyncio.Lock`` so concurrent callers (e.g. webhooks + cron) don't race on
refresh. ``asyncio.Lock`` is the asyncio-native atomic primitive.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable

import structlog
from eth_utils import to_checksum_address
from whaledecode.pools.adapters import get_adapter
from whaledecode.pools.config.loader import get_chain, get_pool_seeds
from whaledecode.pools.models import DexKind, Pool, PoolState, Token
from whaledecode.pools.rpc.manager import ResilientRPCManager
from whaledecode.pools.rpc.multicall import MulticallBatcher, MulticallSpec

log = structlog.get_logger()

# eth_getCode selector — the empty selector is fine because we use the JSON-RPC
# method directly (not a contract call), but we keep the constant here so
# future on-chain code-size probes can read it without a magic number.
GETCODE_METHOD = "eth_getCode"

# Minimum runtime bytecode length to consider a contract "deployed". An empty
# EOA-style response from getCode is "0x" (length 2). Any actual contract is
# at least a few hundred bytes (constructor + fallback).
MIN_BYTECODE_LEN = 100


DiscoveryFn = Callable[[str], Awaitable[list[dict]]]


class PoolRegistry:
    """In-memory pool + state registry, hydrated from seeds + on-chain verification."""

    def __init__(
        self,
        rpc: ResilientRPCManager,
        batcher: MulticallBatcher | None = None,
        seeds: dict[str, list[dict]] | None = None,
    ) -> None:
        self._rpc = rpc
        self._batcher = batcher or MulticallBatcher(rpc=rpc)
        self._seeds = seeds if seeds is not None else get_pool_seeds()
        self._pools: dict[tuple[int, str], Pool] = {}
        self._states: dict[tuple[int, str], PoolState] = {}
        self._lock = asyncio.Lock()

    # ---------- bootstrap ----------

    def bootstrap(self, chains: Iterable[str] | None = None) -> list[Pool]:
        """Materialise Pool objects from ``pool_seeds.json``.

        No network calls — just hydrates the in-memory pool list. Call
        ``verify_and_register`` to gatekeep against real on-chain state.
        """
        chains = list(chains) if chains is not None else list(self._seeds.keys())
        out: list[Pool] = []
        for chain_name in chains:
            cfg = get_chain(chain_name)
            for spec in self._seeds.get(chain_name, []):
                try:
                    pool = self._pool_from_seed(chain_name, cfg.chain_id, spec)
                except (KeyError, ValueError) as exc:
                    log.warning("seed_skipped", extra={"chain": chain_name, "error": str(exc)})
                    continue
                out.append(pool)
        return out

    async def verify_and_register(self, pools: list[Pool]) -> list[Pool]:
        """One Multicall3 batch per chain: confirm bytecode + read initial state.

        Drops pools whose contract is empty / state-call reverts.
        """
        by_chain: dict[int, list[Pool]] = {}
        for p in pools:
            by_chain.setdefault(p.chain_id, []).append(p)

        verified: list[Pool] = []
        for chain_id, chain_pools in by_chain.items():
            chain_name = self._chain_name(chain_id)
            try:
                present = await self._batch_bytecode_present(chain_name, chain_pools)
            except Exception as exc:
                log.warning("bytecode_check_failed", extra={"chain": chain_name, "error": str(exc)})
                present = [True] * len(chain_pools)  # fall back to adapter-only verification

            try:
                states = await self._batch_state(chain_name, chain_pools)
            except Exception as exc:
                log.warning("multicall_state_failed", extra={"chain": chain_name, "error": str(exc)})
                states = [PoolState(p.address, p.chain_id) for p in chain_pools]

            for pool, has_code, state in zip(chain_pools, present, states):
                if not has_code:
                    log.debug("pool_dropped_no_code", extra={"address": pool.address})
                    continue
                if not state.is_alive():
                    log.debug("pool_dropped_zero_state", extra={"address": pool.address})
                    continue
                async with self._lock:
                    self._pools[pool.key] = pool
                    self._states[pool.key] = state
                verified.append(pool)
        log.info("pools_verified", extra={"count": len(verified)})
        return verified

    async def refresh_states(self, chain: str) -> list[PoolState]:
        """Re-fetch state for every verified pool on ``chain`` via one batch."""
        chain_id = get_chain(chain).chain_id
        async with self._lock:
            pools = [p for (cid, _), p in self._pools.items() if cid == chain_id]
        if not pools:
            return []
        states = await self._batch_state(chain, pools)
        async with self._lock:
            for pool, state in zip(pools, states):
                self._states[pool.key] = state
        return states

    # ---------- accessors ----------

    def pools(self, chain: str | None = None) -> list[Pool]:
        with_chain = chain
        out: list[Pool] = []
        for (cid, _addr), p in self._pools.items():
            if with_chain is not None and cid != get_chain(with_chain).chain_id:
                continue
            out.append(p)
        return out

    def state(self, chain: str, address: str) -> PoolState | None:
        return self._states.get((get_chain(chain).chain_id, address.lower()))

    # ---------- internals ----------

    def _pool_from_seed(self, chain_name: str, chain_id: int, spec: dict) -> Pool:
        dex = DexKind(spec["dex"])
        token0 = Token(
            address=to_checksum_address(spec["token0"]),
            symbol=spec.get("symbol0", "TKN0"),
            decimals=int(spec.get("decimals0", 18)),
        )
        token1 = Token(
            address=to_checksum_address(spec["token1"]),
            symbol=spec.get("symbol1", "TKN1"),
            decimals=int(spec.get("decimals1", 18)),
        )
        return Pool(
            address=to_checksum_address(spec["address"]),
            chain_id=chain_id,
            dex=dex,
            token0=token0,
            token1=token1,
            fee_tier=int(spec.get("fee_tier", 0)),
        )

    async def _batch_bytecode_present(self, chain: str, pools: list[Pool]) -> list[bool]:
        """Single multicall-style batch of ``eth_getCode`` calls.

        The cheap alternative to a real multicall: just hit each pool with
        one ``eth_getCode`` concurrently. ``eth_getCode`` isn't aggregatable
        through Multicall3 because the node, not a contract, computes it —
        so concurrency is the best we get. ``ResilientRPCManager`` still
        routes everything through its breaker.
        """
        results = await asyncio.gather(
            *(self._get_code(chain, p.address) for p in pools),
            return_exceptions=True,
        )
        out: list[bool] = []
        for r in results:
            if isinstance(r, Exception):
                out.append(False)
                continue
            out.append(len(r) >= MIN_BYTECODE_LEN)
        return out

    async def _get_code(self, chain: str, address: str) -> str:
        result = await self._rpc.execute(
            chain,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": GETCODE_METHOD,
                "params": [address, "latest"],
            },
        )
        return result if isinstance(result, str) else ""

    async def _batch_state(self, chain: str, pools: list[Pool]) -> list[PoolState]:
        # Build sub-calls in pool-order, then chunk by adapter state-call count.
        specs: list[MulticallSpec] = []
        spec_to_pool: list[Pool] = []
        for pool in pools:
            adapter = get_adapter(pool.dex)
            sub_calls = adapter.encode_state_calls(pool)
            for target, calldata in sub_calls:
                specs.append(MulticallSpec(target=("0x" + target.hex()), calldata=calldata, tag=pool.address))
                spec_to_pool.append(pool)

        # Block number is fetched once (cheap) and stamped onto every state.
        block_number = await self._fetch_block(chain)

        rows = await self._batcher.aggregate3(chain, specs)

        # Group rows by pool, hand each pool's slice to its adapter.
        per_pool_rows: dict[str, list[tuple[bool, bytes]]] = {p.address: [] for p in pools}
        for pool, row in zip(spec_to_pool, rows):
            per_pool_rows[pool.address].append(row)

        out: list[PoolState] = []
        for pool in pools:
            adapter = get_adapter(pool.dex)
            try:
                state = adapter.decode_state(pool, per_pool_rows[pool.address], block_number)
            except Exception as exc:
                log.warning("state_decode_failed", extra={"address": pool.address, "error": str(exc)})
                state = PoolState(pool.address, pool.chain_id, block_number=block_number)
            out.append(state)
        return out

    async def _fetch_block(self, chain: str) -> int:
        from whaledecode.infrastructure.rpc_router import to_int

        raw = await self._rpc.execute(
            chain,
            {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []},
        )
        try:
            return to_int(raw)
        except Exception:
            return 0

    @staticmethod
    def _chain_name(chain_id: int) -> str:
        from whaledecode.pools.config.loader import get_chains

        for name, cfg in get_chains().items():
            if cfg.chain_id == chain_id:
                return name
        raise KeyError(f"Unknown chain_id: {chain_id}")


__all__ = ["DiscoveryFn", "MIN_BYTECODE_LEN", "PoolRegistry"]
