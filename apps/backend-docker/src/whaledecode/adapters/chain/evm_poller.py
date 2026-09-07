"""EVM targeted poller: eth_getLogs with the curated address set pushed into
``topics`` so the node filters server-side — tiny payloads, flat RAM.

Logs are **aggregated per tx_hash**: every Transfer log in a transaction is
decoded (hex value -> token decimals -> USD via the cached price oracle),
summed into one net-USD figure, and gated once against the whale floor.
candidate_events receives exactly one row per qualifying tx_hash, so a 12-log
routing hop costs one ingestion instead of twelve (Aggregation pattern — it
kills log amplification at the source).
"""
from collections import defaultdict
from typing import Any

import structlog
from aiolimiter import AsyncLimiter

from whaledecode.adapters.chain.normalizer import (
    TRANSFER_EVENT_SIGNATURE,
    pad_address_to_topic,
    parse_token_amount,
    unpad_address_from_topic,
)
from whaledecode.adapters.chain.poller import TargetedChainPoller
from whaledecode.adapters.pricing.oracle import PriceOracle
from whaledecode.config.settings import Settings
from whaledecode.domain.entities.curated_wallet import CuratedWallet
from whaledecode.infrastructure.rpc_router import RpcFailoverRouter, to_int

log = structlog.get_logger()

# Public nodes reject wide ranges; cap at 100 blocks to avoid payload size
# limits. On first boot (no cursor) we fall back to a small window.
_MAX_BLOCK_RANGE = 100
_BOOTSTRAP_BLOCK_RANGE = 10

# ponytail: free RPCs return -32046/-32701 on wide topic arrays — 20 addresses
# per eth_getLogs call; shrink further if a node still balks.
_MAX_ADDRESSES_PER_GETLOGS = 20

# ponytail: eth_blockNumber is queried once per chain per poll loop; with a
# 25s interval that hits the node 1+ times just to learn the head. Cache for
# 12s so concurrent EVM/BASE/ARB passes share the same head — saves one
# RPC per chain per cycle on a tight loop.
_BLOCK_HEAD_CACHE_SECONDS = 12.0

# ponytail: per-call eth_getLogs block span stays strictly under the 10-block
# limit (dRPC returns -32600 above 10 blocks; some L2 public nodes do the
# same). 9 leaves one block of headroom in case the node rounds up.
MAX_LOGS_RANGE_PER_CALL = 9

# eth_call selector for decimals() on an ERC-20 contract.
_DECIMALS_SELECTOR = "0x313ce567"


def _transfer_topic_queries(padded: list[str]) -> list[list[Any]]:
    """Outgoing ([SIG, wallets, null]) then incoming ([SIG, null, wallets]).

    Addresses are chunked so no single call carries more than
    ``_MAX_ADDRESSES_PER_GETLOGS`` topics (free-RPC topic-array limits).
    """
    chunks = [
        padded[i : i + _MAX_ADDRESSES_PER_GETLOGS]
        for i in range(0, len(padded), _MAX_ADDRESSES_PER_GETLOGS)
    ]
    return [
        [TRANSFER_EVENT_SIGNATURE, chunk, None]
        for chunk in chunks
    ] + [
        [TRANSFER_EVENT_SIGNATURE, None, chunk]
        for chunk in chunks
    ]


def _wallet_from_topics(
    topics: list[str], padded_to_wallet: dict[str, "CuratedWallet"]
) -> "CuratedWallet | None":
    """Map a Transfer log's topics to the tracked CuratedWallet (from or to side).

    ponytail: same lookup logic as ``wallet_id_from_transfer_topics`` but returns
    the full wallet object so we can stamp ``wallet_address`` on the activity
    without an extra DB round-trip.
    """
    for idx in (1, 2):
        if idx < len(topics) and topics[idx]:
            wallet_obj = padded_to_wallet.get(topics[idx].lower())
            if wallet_obj is not None:
                return wallet_obj
    return None


class EvmTargetedPoller(TargetedChainPoller):
    def __init__(
        self,
        chain_code: str,
        chain_label: str,
        router: RpcFailoverRouter,
        price_oracle: PriceOracle | None = None,
        rate_limiter: AsyncLimiter | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._chain_code = chain_code
        self._chain_label = chain_label
        self._router = router
        self._oracle = price_oracle or PriceOracle()
        self._rate_limiter = rate_limiter
        self._settings = settings
        self._decimals_cache: dict[str, int] = {}
        self._last_block: int | None = None  # in-memory cursor; dedupe_key guards re-ingest after restart
        # ponytail: short-lived block-head cache. (timestamp, head) — the head
        # is reused across concurrent passes until the TTL expires.
        self._head_cache: tuple[float, int] | None = None

    async def _head_block(self) -> int:
        """``eth_blockNumber`` with a 12s TTL so concurrent EVM/BASE/ARB passes
        share the same head instead of burning an RPC each.
        """
        import time as _time

        if self._head_cache is not None:
            ts, head = self._head_cache
            if _time.monotonic() - ts < _BLOCK_HEAD_CACHE_SECONDS:
                return head
        head_hex = await self._rpc("eth_blockNumber", [])
        head = to_int(head_hex)
        self._head_cache = (_time.monotonic(), head)
        return head

    def _max_block_range(self) -> int:
        """Hard ceiling of MAX_LOGS_RANGE_PER_CALL blocks per eth_getLogs call.

        The settings.MAX_GET_LOGS_BLOCK_RANGE dict can request larger windows
        for fast L2s, but individual nodes (dRPC, public free providers) reject
        ranges above 10 blocks with -32600. We clamp to 9 unconditionally.
        """
        return MAX_LOGS_RANGE_PER_CALL

    async def _rpc(self, method: str, params: list[Any]) -> Any:
        if self._rate_limiter is not None:
            await self._rate_limiter.acquire()
        return await self._router.post({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})

    async def _token_decimals(self, contract: str) -> int:
        """ERC-20 ``decimals()`` via eth_call; cached for the process lifetime."""
        cached = self._decimals_cache.get(contract)
        if cached is not None:
            return cached
        try:
            raw = await self._rpc(
                "eth_call", [{"to": contract, "data": _DECIMALS_SELECTOR}, "latest"]
            )
            decimals = to_int(raw) if raw and raw != "0x" else 18
            if not 0 <= decimals <= 36:
                decimals = 18
        except Exception:  # noqa: BLE001 - unpriceable token must not kill the pass
            decimals = 18
        self._decimals_cache[contract] = decimals
        return decimals

    async def _log_usd_value(self, raw_log: dict[str, Any]) -> float:
        """Decode one ERC-20 Transfer log into real USD (never the native `value` field)."""
        contract = str(raw_log.get("address", "")).lower()
        price = await self._oracle.get_token_price_usd(contract, self._chain_label.lower())
        if price <= 0.0:
            return 0.0
        amount = parse_token_amount(raw_log.get("data", "0x0"), await self._token_decimals(contract))
        return price * amount

    async def fetch_recent_activity(self, targets: list[CuratedWallet]) -> list[dict[str, Any]]:
        if not targets:
            return []
        head = await self._head_block()

        # Range-based query: start from last_polled_block + 1 (or bootstrap
        # window on first call). Cap at chain-specific max range to stay within
        # public-node payload size limits.
        if self._last_block is not None:
            from_block = self._last_block + 1
        else:
            from_block = head - _BOOTSTRAP_BLOCK_RANGE
        to_block = head - 1  # skip the not-yet-final tip
        # Enforce max range cap — trim from_block if the gap is too wide.
        max_range = self._max_block_range()
        if to_block - from_block >= max_range:
            from_block = to_block - max_range + 1

        padded_to_wallet = {
            pad_address_to_topic(w.address): w for w in targets if w.id is not None
        }
        padded = list(padded_to_wallet.keys())

        # Aggregate raw logs by transaction before any pricing/gating.
        by_tx: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"logs": [], "wallet_id": None, "wallet_address": "", "from": "", "to": ""}
        )
        for topics in _transfer_topic_queries(padded):
            logs = await self._rpc(
                "eth_getLogs",
                [{"fromBlock": hex(from_block), "toBlock": hex(to_block), "topics": topics}],
            )
            for raw in logs or []:
                log_topics = raw.get("topics", [])
                wallet_obj = _wallet_from_topics(log_topics, padded_to_wallet)
                if wallet_obj is None or wallet_obj.id is None:
                    continue
                tx_hash = str(raw.get("transactionHash", ""))
                entry = by_tx[tx_hash]
                entry["logs"].append(raw)
                if entry["wallet_id"] is None:
                    entry["wallet_id"] = wallet_obj.id
                    entry["wallet_address"] = wallet_obj.address
                # Stamp the counterparty so downstream enrichment (_counterparty
                # in investigation.py, profiler enrich, telemetry) never falls
                # through to a "" SQL bind parameter.
                if len(log_topics) > 1 and not entry["from"]:
                    entry["from"] = unpad_address_from_topic(log_topics[1])
                if len(log_topics) > 2 and not entry["to"]:
                    entry["to"] = unpad_address_from_topic(log_topics[2])

        activities: list[dict[str, Any]] = []
        for tx_hash, entry in by_tx.items():
            usd_values = [await self._log_usd_value(entry_log) for entry_log in entry["logs"]]
            net_usd = sum(usd_values)
            if net_usd <= 0.0:
                continue
            wallet_id = entry["wallet_id"]
            wallet_address = entry["wallet_address"]
            assert wallet_id is not None
            assert wallet_address, "poller must stamp wallet_address on every activity"
            activities.append({
                "wallet_id": wallet_id,
                "wallet_address": wallet_address,
                "chain": self._chain_label,
                "tx_hash": tx_hash,
                "log_index": 0,  # aggregated row: one per tx, not per log
                "block_number": max(to_int(entry_log.get("blockNumber", "0x0")) for entry_log in entry["logs"]),
                "event_type": "TRANSFER",
                "value_usd": net_usd,
                "raw_json": {
                    "tx_hash": tx_hash,
                    "value_usd": net_usd,
                    "log_count": len(entry["logs"]),
                    "from": entry["from"],
                    "to": entry["to"],
                    "logs": entry["logs"],
                },
                "score": 0.0,
                "dedupe_key": f"{wallet_id}:{tx_hash}:agg",
            })

        self._last_block = to_block
        log.info(
            "evm_poll_complete",
            extra={"chain": self._chain_code, "targets": len(targets), "txs": len(activities),
                   "range": [from_block, to_block]},
        )
        return activities

    async def aclose(self) -> None:
        await self._oracle.aclose()
