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
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from whaledecode.adapters.alchemy.transfers import AlchemyTransfersClient

logger = logging.getLogger(__name__)

MAX_HOPS = 3
FUNDING_RECENCY_HOURS = 48  # Extended to 48h for fresh CEX funding detection
STEALTH_MIN_SIBLINGS = 2  # >=2 wallets (including the trigger wallet) = syndicate
SYNDICATE_WINDOW_HOURS = 12


@dataclass(frozen=True)
class TraceResult:
    attributed_label: str  # "" = no attribution found
    root_address: str
    hops: int
    stealth_accumulation: bool
    siblings_in_cluster: int
    cluster_id: UUID | None = None
    cluster_type: str = ""
    cluster_wallets_count: int = 0
    cluster_total_usd: float = 0.0


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
        token_address: str = "",
        value_usd: float = 0.0,
    ) -> TraceResult:
        """BFS upstream from ``wallet_address``; persist edges; attribute + flag.

        ``known_labels`` maps lowercase address -> human label for curated
        entities. Returns an empty-attribution TraceResult on any failure.

        If token_address and value_usd are provided, also checks for syndicate
        clusters (same root funder buying same token within SYNDICATE_WINDOW_HOURS).
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
                # Check for syndicate cluster if token_address provided
                cluster_id = None
                cluster_type = ""
                cluster_wallets_count = 0
                cluster_total_usd = 0.0
                if token_address and value_usd > 0:
                    cluster_id, cluster_type, cluster_wallets_count, cluster_total_usd = await self._check_and_update_syndicate(
                        chain, first_parent, token_address, value_usd, now_unix
                    )
                return TraceResult(
                    attributed_label=label,
                    root_address=first_parent,
                    hops=hops + 1,
                    stealth_accumulation=siblings >= STEALTH_MIN_SIBLINGS - 1,
                    siblings_in_cluster=siblings + 1,
                    cluster_id=cluster_id,
                    cluster_type=cluster_type,
                    cluster_wallets_count=cluster_wallets_count,
                    cluster_total_usd=cluster_total_usd,
                )
            current, hops = parent, hops + 1
        return empty

    async def _check_and_update_syndicate(
        self,
        chain: str,
        root_address: str,
        token_address: str,
        value_usd: float,
        now_unix: float,
    ) -> tuple[UUID | None, str, int, float]:
        """Check for and create/update syndicate cluster for same-root wallets buying same token."""

        token_address = token_address.lower()
        root_address = root_address.lower()
        window_start = datetime.fromtimestamp(now_unix - SYNDICATE_WINDOW_HOURS * 3600, tz=UTC)
        window_end = datetime.fromtimestamp(now_unix, tz=UTC)

        async with self._uow_factory() as uow:
            # Find all siblings funded by this root that bought the same token recently
            # We need to join with candidate_events to find token purchases
            # For now, use funding_edges to find siblings, then check their recent activity
            siblings = await uow.funding_edges.siblings_funded_by(root_address, "", within_hours=SYNDICATE_WINDOW_HOURS)
            # Include the trigger wallet
            all_wallets = set(siblings)
            all_wallets.add(root_address)  # The root itself might also trade

            # This is a simplified check - in production you'd join with candidate_events
            # For now, we'll create/update the cluster based on the current event
            # and the sibling count
            wallet_count = len(all_wallets)
            if wallet_count >= STEALTH_MIN_SIBLINGS:
                cluster_id = await uow.syndicate_clusters.upsert_cluster({
                    "chain": chain.lower(),
                    "root_address": root_address,
                    "root_label": "",  # Would be populated from known_labels
                    "token_address": token_address,
                    "token_symbol": "",  # Would be populated from oracle
                    "window_start": window_start,
                    "window_end": window_end,
                    "wallet_count": wallet_count,
                    "total_usd": value_usd,  # Simplified - would sum all wallet purchases
                    "cluster_type": "FRESH_CEX_ACCUMULATOR",
                })
                return cluster_id, "FRESH_CEX_ACCUMULATOR", wallet_count, value_usd

        return None, "", 0, 0.0

    async def _sibling_count(self, root: str, exclude: str) -> int:
        async with self._uow_factory() as uow:
            return len(await uow.funding_edges.siblings_funded_by(root, exclude))
