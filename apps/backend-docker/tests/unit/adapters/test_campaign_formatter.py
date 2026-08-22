from whaledecode.adapters.db.models.campaign import CampaignModel
from whaledecode.adapters.telegram.formatters.campaign_formatter import (
    format_mutated_campaign_alert,
    format_threaded_campaign_alert,
)
from whaledecode.domain.entities.candidate_event import CandidateEvent
from whaledecode.domain.value_objects.hash import Hash


def _campaign(**kw) -> CampaignModel:
    return CampaignModel(
        wallet_id=1,
        chain="ethereum",
        token_address="0x1234",
        total_usd_value=150_000.0,
        event_count=2,
        status="active",
        telegram_message_id=123,
        **kw,
    )


def _event() -> CandidateEvent:
    return CandidateEvent(
        wallet_id=1,
        chain="ethereum",
        tx_hash=Hash("0x" + "ab" * 32),
        log_index=0,
        block_number=100,
        raw_json={"value_usd": 50_000.0, "asset": "USDC"},
        score=80.0,
        dedupe_key="x",
    )


class TestMutated:
    def test_escalation_header_and_total(self):
        html = format_mutated_campaign_alert(_campaign())
        assert "WHALE CAMPAIGN ESCALATION" in html
        assert "2 TXs" in html
        assert "$150,000.00 USD" in html

    def test_chain_label(self):
        html = format_mutated_campaign_alert(_campaign())
        assert "ETHEREUM" in html


class TestThreaded:
    def test_latest_and_cumulative(self):
        html = format_threaded_campaign_alert(_event(), _campaign())
        assert "CAMPAIGN EXPANSION UPDATE" in html
        assert "+$50,000.00 USD" in html
        assert "$150,000.00 USD" in html
        assert "(2 Total Transfers)" in html
