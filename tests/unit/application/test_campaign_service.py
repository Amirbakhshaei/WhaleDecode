"""Campaign dual-publishing strategy tests.

Covers the spec checklist:
1. Single transfer -> new Campaign + CREATED.
2. Same wallet 5 min later -> in-window accumulation -> MUTATED.
3. Event past the 30-min window -> THREADED anchored reply.
"""
from datetime import UTC, datetime, timedelta

import pytest
from whaledecode.application.services.campaign_service import (
    BLACK_SWAN_THRESHOLD_USD,
    CAMPAIGN_WINDOW_MINUTES,
    CampaignService,
)
from whaledecode.domain.entities.candidate_event import CandidateEvent
from whaledecode.domain.value_objects.hash import Hash


def _event(dedupe: str, value_usd: float, wallet_id: int = 1) -> CandidateEvent:
    return CandidateEvent(
        wallet_id=wallet_id,
        chain="Ethereum",
        tx_hash=Hash("0x" + dedupe.zfill(64)),
        log_index=0,
        block_number=100,
        event_type="TRANSFER",
        raw_json={"value_usd": value_usd, "rawContract": {"address": "0x1234"}},
        score=80.0,
        dedupe_key=dedupe,
    )


@pytest.mark.asyncio
async def test_single_transfer_creates_campaign(db_session):
    event = _event("a", 120_000.0)

    campaign, action = await CampaignService.resolve_event_campaign(db_session, event)
    await db_session.commit()

    assert action == "CREATED"
    assert campaign.id is not None
    assert campaign.total_usd_value == 120_000.0
    assert campaign.event_count == 1
    assert campaign.status == "active"
    assert event.campaign_id == campaign.id
    assert campaign.token_address == "0x1234"


@pytest.mark.asyncio
async def test_second_transfer_within_window_mutates(db_session):
    first = _event("a", 100_000.0)
    campaign, action = await CampaignService.resolve_event_campaign(db_session, first)
    # force created_at into the past so a follow-up stays inside the window
    campaign.created_at = datetime.now(UTC) - timedelta(minutes=1)
    campaign.updated_at = datetime.now(UTC)
    await db_session.commit()

    second = _event("b", 50_000.0)
    campaign, action = await CampaignService.resolve_event_campaign(db_session, second)
    await db_session.commit()

    assert action == "MUTATED"
    assert campaign.event_count == 2
    assert campaign.total_usd_value == 150_000.0
    assert second.campaign_id == campaign.id


@pytest.mark.asyncio
async def test_third_transfer_after_window_threads(db_session):
    first = _event("a", 100_000.0)
    campaign, action = await CampaignService.resolve_event_campaign(db_session, first)
    # created > 30 min ago but recently updated (still found by the window query)
    campaign.created_at = datetime.now(UTC) - timedelta(minutes=CAMPAIGN_WINDOW_MINUTES + 5)
    campaign.updated_at = datetime.now(UTC)
    await db_session.commit()

    third = _event("c", 50_000.0)
    campaign, action = await CampaignService.resolve_event_campaign(db_session, third)
    await db_session.commit()

    assert action == "THREADED"
    assert campaign.event_count == 2
    assert campaign.total_usd_value == 150_000.0


@pytest.mark.asyncio
async def test_black_swan_crossing_threads(db_session):
    first = _event("a", BLACK_SWAN_THRESHOLD_USD - 100_000.0)
    campaign, action = await CampaignService.resolve_event_campaign(db_session, first)
    campaign.created_at = datetime.now(UTC) - timedelta(minutes=1)
    campaign.updated_at = datetime.now(UTC)
    await db_session.commit()

    spike = _event("b", 150_000.0)  # crosses $2M
    campaign, action = await CampaignService.resolve_event_campaign(db_session, spike)
    await db_session.commit()

    assert action == "THREADED"
    assert campaign.total_usd_value > BLACK_SWAN_THRESHOLD_USD
