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
from whaledecode.adapters.chain.normalizer import (
    TRANSFER_EVENT_SIGNATURE,
    pad_address_to_topic,
    parse_token_amount,
    wallet_id_from_transfer_topics,
)
from whaledecode.adapters.chain.poller import TargetedChainPoller
from whaledecode.adapters.pricing.oracle import PriceOracle
from whaledecode.domain.entities.curated_wallet import CuratedWallet
from whaledecode.infrastructure.rpc_router import RpcFailoverRouter, to_int

log = structlog.get_logger()

# Public nodes reject wide ranges; stay small and catch up across polls.
_DEFAULT_BLOCK_RANGE = 10

# ponytail: free RPCs return -32046/-32701 on wide topic arrays — 20 addresses
# per eth_getLogs call; shrink further if a node still balks.
_MAX_ADDRESSES_PER_GETLOGS = 20

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


class EvmTargetedPoller(TargetedChainPoller):
    def __init__(
        self,
        chain_code: str,
        chain_label: str,
        router: RpcFailoverRouter,
        price_oracle: PriceOracle | None = None,
    ) -> None:
        self._chain_code = chain_code
        self._chain_label = chain_label
        self._router = router
        self._oracle = price_oracle or PriceOracle()
        self._decimals_cache: dict[str, int] = {}
        self._last_block: int | None = None  # in-memory cursor; dedupe_key guards re-ingest after restart

    async def _rpc(self, method: str, params: list[Any]) -> Any:
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
        head_hex = await self._rpc("eth_blockNumber", [])
        head = to_int(head_hex)

        # ponytail: fixed small range instead of persisted cursors — a restart
        # re-scans one window at worst; add a cursor table if gaps ever matter.
        from_block = head - _DEFAULT_BLOCK_RANGE
        if self._last_block is not None:
            from_block = max(from_block, min(self._last_block + 1, head))
        to_block = head - 1  # skip the not-yet-final tip

        padded_to_wallet = {
            pad_address_to_topic(w.address): w.id for w in targets if w.id is not None
        }
        padded = list(padded_to_wallet.keys())

        # Aggregate raw logs by transaction before any pricing/gating.
        by_tx: dict[str, dict[str, Any]] = defaultdict(lambda: {"logs": [], "wallet_id": None})
        for topics in _transfer_topic_queries(padded):
            logs = await self._rpc(
                "eth_getLogs",
                [{"fromBlock": hex(from_block), "toBlock": hex(to_block), "topics": topics}],
            )
            for raw in logs or []:
                wallet_id = wallet_id_from_transfer_topics(raw.get("topics", []), padded_to_wallet)
                if wallet_id is None:
                    continue
                tx_hash = str(raw.get("transactionHash", ""))
                entry = by_tx[tx_hash]
                entry["logs"].append(raw)
                if entry["wallet_id"] is None:
                    entry["wallet_id"] = wallet_id

        activities: list[dict[str, Any]] = []
        for tx_hash, entry in by_tx.items():
            usd_values = [await self._log_usd_value(entry_log) for entry_log in entry["logs"]]
            net_usd = sum(usd_values)
            if net_usd <= 0.0:
                continue
            wallet_id = entry["wallet_id"]
            assert wallet_id is not None
            activities.append({
                "wallet_id": wallet_id,
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
