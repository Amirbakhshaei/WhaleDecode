"""HTML message builders for the campaign dual-publishing strategy.

The CREATED vector reuses the existing rich Glass Whale briefing
(channel_formatter.format_alert) — it carries the LLM summary. Only the
MUTATED (in-place edit) and THREADED (anchored reply) escalation formats
live here.
"""
from __future__ import annotations

from html import escape

from whaledecode.adapters.db.models.campaign import CampaignModel
from whaledecode.domain.entities.candidate_event import CandidateEvent


def format_mutated_campaign_alert(campaign: CampaignModel) -> str:
    return (
        f"🔄 <b>WHALE CAMPAIGN ESCALATION ({campaign.event_count} TXs) 🐳</b>\n\n"
        f"💰 <b>Total Campaign Volume:</b> <b>${campaign.total_usd_value:,.2f} USD</b>\n"
        f"🌐 <b>Chain:</b> {escape(campaign.chain.upper())}\n"
        f"📊 <b>Transactions Consolidated:</b> {campaign.event_count}\n"
        f"🧠 <b>Status:</b> Active Smart Money Accumulation\n\n"
        f"🤖 Deep Dive with AI: @WhaleDecodeBot"
    )


def format_threaded_campaign_alert(event: CandidateEvent, campaign: CampaignModel) -> str:
    latest_usd = float(event.raw_json.get("value_usd") or 0.0)
    return (
        f"🚨 <b>CAMPAIGN EXPANSION UPDATE</b> 🐳\n\n"
        f"This whale entity has continued execution:\n"
        f"➕ <b>Latest TX:</b> +${latest_usd:,.2f} USD\n"
        f"📊 <b>Cumulative Volume:</b> <b>${campaign.total_usd_value:,.2f} USD</b> "
        f"({campaign.event_count} Total Transfers)\n\n"
        f"🤖 Deep Dive with AI: @WhaleDecodeBot"
    )
