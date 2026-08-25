"""Ingestion decoder: value gating, velocity telemetry, and passive attribution.

Runs on every whale transaction before LLM synthesis:
  * Value threshold — drop sub-$MIN_ALERT_USD_THRESHOLD moves (no LLM, no alert).
  * Velocity telemetry — increment per-address 30d tx count + decay penalty so
    the daily rotation can demote spammy/bot wallets.
  * Passive attribution — resolve sender/recipient labels locally from Postgres
    (case-insensitive) instead of spending CUs on chain lookups.
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from whaledecode.adapters.db.repositories.curated_wallet import CuratedWalletRepository
from whaledecode.config.settings import Settings
from whaledecode.domain.entities.curated_wallet import CuratedWallet

logger = logging.getLogger(__name__)

DEFAULT_MIN_ALERT_USD_THRESHOLD = 50_000.0

_VELOCITY_UPDATE = text(
    """
    UPDATE curated_wallets
    SET tx_count_30d = tx_count_30d + 1,
        last_activity_at = CURRENT_TIMESTAMP,
        velocity_penalty = CASE
            WHEN tx_count_30d > 400 THEN 0.2  -- bot / spam penalty
            ELSE 1.0
        END
    WHERE lower(address) = lower(:address)
    """
)


def min_alert_threshold(settings: Settings) -> float:
    return float(getattr(settings, "MIN_ALERT_USD_THRESHOLD", DEFAULT_MIN_ALERT_USD_THRESHOLD))


def is_above_value_threshold(value_usd: float, settings: Settings) -> bool:
    """True when the move clears the global noise floor and is worth an LLM pass."""
    if value_usd is None:
        return False
    return float(value_usd) >= min_alert_threshold(settings)


async def apply_velocity_telemetry(session: AsyncSession, addresses: list[str]) -> None:
    """Bump 30d tx count + decay penalty for each (case-insensitive) address.

    Best-effort: callers wrap this so a telemetry failure never blocks ingestion.
    """
    seen: set[str] = set()
    for addr in addresses:
        if not addr:
            continue
        lowered = addr.lower().strip()
        if lowered in seen:
            continue
        seen.add(lowered)
        await session.execute(_VELOCITY_UPDATE, {"address": lowered})


async def resolve_entity(session: AsyncSession, address: str) -> CuratedWallet | None:
    """Passive attribution: resolve a label for ``address`` from Postgres only.

    Case-insensitive (the repo lowercases) and restricted to ``is_active`` wallets
    so dormant/excluded entities never get attributed to a live whale move.
    """
    if not address:
        return None
    repo = CuratedWalletRepository(session)
    matches = await repo.find_by_addresses([address])
    active = [m for m in matches if m.is_active]
    return active[0] if active else None


class TransactionDecoderService:
    """Deprecated with the Alchemy webhook route.

    On-chain ingestion now flows through the Targeted Failover Poller
    (``whaledecode.entrypoints.poller``). The parsing helpers that used to
    back this facade live on in ``entrypoints.webhook`` as reference logic.
    """
