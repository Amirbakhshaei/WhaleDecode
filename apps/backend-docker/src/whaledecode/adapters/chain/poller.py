"""Targeted polling interface — the seam between chain syntax and orchestration.

The worker only ever calls ``fetch_recent_activity(targets)`` and consumes the
standard activity dict (the same shape ``candidate_events.create_pending``
accepts). Chain-specific RPC grammar lives entirely behind this boundary
(Interface Segregation): adding a chain means adding an adapter, nothing else.
"""
import asyncio
from abc import ABC, abstractmethod
from typing import Any

from whaledecode.domain.entities.curated_wallet import CuratedWallet

# Standard output contract: keys required by candidate_events.create_pending.
#   wallet_id, chain, tx_hash, log_index, block_number, event_type,
#   raw_json, score, dedupe_key


async def backoff_sleep(seconds: float, stop_event: asyncio.Event | None = None) -> None:
    """Sleep that wakes immediately on shutdown."""
    if stop_event is not None:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=seconds)
        except TimeoutError:
            pass
    else:
        await asyncio.sleep(seconds)


class TargetedChainPoller(ABC):
    """Polls only the addresses we track; never scans the whole chain."""

    @abstractmethod
    async def fetch_recent_activity(self, targets: list[CuratedWallet]) -> list[dict[str, Any]]:
        """Return normalized activities for the given target wallets since last poll.

        Implementations must be idempotent per call window (cursors / dedupe
        keys) so a repeated pass after a crash re-ingests nothing twice.
        """
