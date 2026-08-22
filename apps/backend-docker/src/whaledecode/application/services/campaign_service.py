"""Stateful campaign aggregation: group related whale transfers into a Campaign.

Decides the delivery vector for each incoming event — CREATED (initial post),
MUTATED (edit in place), or THREADED (anchored reply) — based on the 30-minute
campaign window and the $2M black-swan threshold.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from whaledecode.adapters.db.models.campaign import CampaignModel
from whaledecode.domain.entities.candidate_event import CandidateEvent

logger = logging.getLogger(__name__)

CAMPAIGN_WINDOW_MINUTES = 30
BLACK_SWAN_THRESHOLD_USD = 2_000_000.0


class CampaignService:
    @staticmethod
    async def resolve_event_campaign(
        session: AsyncSession, event: CandidateEvent
    ) -> tuple[CampaignModel, str]:
        """Evaluate one candidate event against active campaigns.

        Returns ``(campaign, action)`` where action is one of
        ``CREATED`` | ``MUTATED`` | ``THREADED``. The campaign is created or
        accumulated (total_usd_value / event_count) and ``event.campaign_id``
        is stamped, but nothing is committed — the caller owns the transaction.
        """
        event_usd = float(event.raw_json.get("value_usd") or 0.0)
        cutoff = datetime.now(UTC) - timedelta(minutes=CAMPAIGN_WINDOW_MINUTES)

        stmt = (
            select(CampaignModel)
            .where(
                CampaignModel.wallet_id == event.wallet_id,
                CampaignModel.chain == event.chain,
                CampaignModel.status == "active",
                CampaignModel.updated_at >= cutoff,
            )
            .order_by(CampaignModel.updated_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        campaign = result.scalar_one_or_none()

        if campaign is None:
            campaign = CampaignModel(
                wallet_id=event.wallet_id,
                chain=event.chain,
                token_address=_token_address(event),
                total_usd_value=event_usd,
                event_count=1,
                status="active",
            )
            session.add(campaign)
            await session.flush()
            event.campaign_id = campaign.id
            return campaign, "CREATED"

        # Accumulate state on the existing campaign.
        # created_at may come back offset-naive from SQLite; normalize before comparing.
        created_at = campaign.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        time_since_creation = datetime.now(UTC) - created_at
        campaign.total_usd_value += event_usd
        campaign.event_count += 1
        event.campaign_id = campaign.id

        in_window = time_since_creation <= timedelta(minutes=CAMPAIGN_WINDOW_MINUTES)
        under_black_swan = campaign.total_usd_value < BLACK_SWAN_THRESHOLD_USD
        if in_window and under_black_swan:
            return campaign, "MUTATED"
        return campaign, "THREADED"


def _token_address(event: CandidateEvent) -> str | None:
    raw = event.raw_json if isinstance(event.raw_json, dict) else {}
    contract = raw.get("rawContract") or {}
    return contract.get("address")
