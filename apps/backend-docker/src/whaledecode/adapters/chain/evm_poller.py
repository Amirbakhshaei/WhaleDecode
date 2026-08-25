"""EVM targeted poller: eth_getLogs with the curated address set pushed into
``topics`` so the node filters server-side and returns only matching Transfer
logs — tiny payloads, flat RAM regardless of chain activity volume.
"""
import asyncio
from typing import Any

import structlog
from whaledecode.adapters.chain.normalizer import (
    TRANSFER_EVENT_SIGNATURE,
    normalize_log,
    pad_address_to_topic,
    wallet_id_from_transfer_topics,
)
from whaledecode.adapters.chain.poller import TargetedChainPoller
from whaledecode.domain.entities.curated_wallet import CuratedWallet
from whaledecode.infrastructure.rpc_router import RpcFailoverRouter

log = structlog.get_logger()

# Public nodes reject wide ranges; stay small and catch up across polls.
_DEFAULT_BLOCK_RANGE = 10


def _transfer_topic_queries(padded: list[str]) -> list[list[Any]]:
    """Outgoing ([SIG, wallets, null]) then incoming ([SIG, null, wallets])."""
    return [
        [TRANSFER_EVENT_SIGNATURE, padded, None],
        [TRANSFER_EVENT_SIGNATURE, None, padded],
    ]


class EvmTargetedPoller(TargetedChainPoller):
    def __init__(self, chain_code: str, chain_label: str, router: RpcFailoverRouter) -> None:
        self._chain_code = chain_code
        self._chain_label = chain_label
        self._router = router
        self._last_block: int | None = None  # in-memory cursor; re-poll window on restart is acceptable (dedupe_key guards)

    async def _rpc(self, method: str, params: list[Any]) -> Any:
        return await self._router.post({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})

    async def fetch_recent_activity(self, targets: list[CuratedWallet]) -> list[dict[str, Any]]:
        if not targets:
            return []
        head_hex = await self._rpc("eth_blockNumber", [])
        head = int(head_hex, 16)

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

        activities: list[dict[str, Any]] = []
        for topics in _transfer_topic_queries(padded):
            logs = await self._rpc(
                "eth_getLogs",
                [{"fromBlock": hex(from_block), "toBlock": hex(to_block), "topics": topics}],
            )
            for raw in logs or []:
                wallet_id = wallet_id_from_transfer_topics(raw.get("topics", []), padded_to_wallet)
                if wallet_id is None:
                    continue
                event = normalize_log(raw, wallet_id, self._chain_label)
                activities.append(event)

        self._last_block = to_block
        log.info(
            "evm_poll_complete",
            extra={"chain": self._chain_code, "targets": len(targets), "found": len(activities),
                   "range": [from_block, to_block]},
        )
        return activities


async def probe_head(router: RpcFailoverRouter) -> int:
    """Health helper: current block number, or raises."""
    return int(await router.post({"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}), 16)


async def backoff_sleep(seconds: float, stop_event: asyncio.Event | None = None) -> None:
    """Sleep that wakes immediately on shutdown."""
    if stop_event is not None:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=seconds)
        except TimeoutError:
            pass
    else:
        await asyncio.sleep(seconds)
