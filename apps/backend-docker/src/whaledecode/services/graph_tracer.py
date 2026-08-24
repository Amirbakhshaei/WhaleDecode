"""Multi-Hop Graph Clustering & Stealth Accumulation Engine (Module 2).

When an unlabeled wallet fires a high-conviction event, trace its genesis
funding source 1-3 hops upstream via Alchemy Transfers, attribute the child to
a labeled root ("Child of Paradigm Sub-wallet [Cluster #412]"), and flag
stealth accumulation when >= 3 sibling wallets funded by the same root buy the
same asset inside the window.

All writes are idempotent (ON CONFLICT DO NOTHING); all reads fail soft.
"""
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from whaledecode.adapters.alchemy.transfers import AlchemyTransfersClient

logger = logging.getLogger(__name__)

MAX_HOPS = 3
FUNDING_RECENCY_HOURS = 24
STEALTH_MIN_SIBLINGS = 3


@dataclass(frozen=True)
class TraceResult:
    attributed_label: str  # "" = no attribution found
    root_address: str
    hops: int
    stealth_accumulation: bool
    siblings_in_cluster: int


def _pick_genesis_transfer(transfers: list[dict[str, Any]], now_unix: float) -> dict[str, Any] | None:
    """The largest inbound transfer within the recency window."""
    cutoff_ms = (now_unix - FUNDING_RECENCY_HOURS * 3600) * 1000
    eligible = [
        t
        for t in transfers
        if t.get("from") and t.get("hash") and (t.get("metadata") or {}).get("blockTimestamp", 0) >= cutoff_ms
        and str(t.get("from", "")).lower() != str(t.get("to", "")).lower()
    ]
    return max(eligible, key=lambda t: float(t.get("value") or 0.0), default=None)


class GraphTracer:
    def __init__(
        self,
        uow_factory: Callable[[], Any],
        transfers_client: AlchemyTransfersClient | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._client = transfers_client

    async def trace(
        self,
        chain: str,
        wallet_address: str,
        *,
        known_labels: dict[str, str],
        now_unix: float,
    ) -> TraceResult:
        """BFS upstream from ``wallet_address``; persist edges; attribute + flag.

        ``known_labels`` maps lowercase address -> human label for curated
        entities. Returns an empty-attribution TraceResult on any failure.
        """
        empty = TraceResult("", "", 0, False, 0)
        wallet_address = (wallet_address or "").strip().lower()
        if not wallet_address or self._client is None:
            return empty

        current, hops = wallet_address, 0
        first_parent = ""
        while hops < MAX_HOPS:
            transfers = await self._client.incoming_transfers(chain, current)
            genesis = _pick_genesis_transfer(transfers, now_unix)
            if genesis is None:
                break
            parent = str(genesis["from"]).lower()
            if not first_parent:
                first_parent = parent
            label = known_labels.get(parent, "")
            # Root = the child's direct funder; siblings cluster under it even
            # when attribution was found deeper in the chain.
            root = first_parent
            async with self._uow_factory() as uow:
                await uow.funding_edges.insert_edge(
                    {
                        "chain": chain.lower(),
                        "child_address": current,
                        "parent_address": parent,
                        "tx_hash": str(genesis["hash"]),
                        "hops_from_root": hops + 1,
                        "root_address": root,
                        "root_label": known_labels.get(root, ""),
                    }
                )
                await uow.commit()
            if label:
                siblings = await self._sibling_count(first_parent, wallet_address)
                return TraceResult(
                    attributed_label=label,
                    root_address=first_parent,
                    hops=hops + 1,
                    stealth_accumulation=siblings >= STEALTH_MIN_SIBLINGS - 1,
                    siblings_in_cluster=siblings + 1,
                )
            current, hops = parent, hops + 1
        return empty

    async def _sibling_count(self, root: str, exclude: str) -> int:
        async with self._uow_factory() as uow:
            return len(await uow.funding_edges.siblings_funded_by(root, exclude))
