from html import escape
from typing import Any

from whaledecode.adapters.telegram.formatters.channel_formatter import (
    format_premium_event_post,
    strip_hex_text,
)
from whaledecode.config.settings import Settings


class RelayFormatter:
    def __init__(self, settings: Settings | None = None) -> None:
        self._disclaimer = settings.DISCLAIMER_TEXT if settings else "Not financial advice. DYOR."

    def format_alert(self, event: dict[str, Any], report: dict[str, Any]) -> str:
        wallet_label = escape(event.get("label", "Unknown Wallet"))
        addr = event.get("address", "")
        addr_short = f"{addr[:6]}...{addr[-4:]}" if len(addr) > 10 else escape(addr)
        chain = escape(event.get("chain", ""))
        event_type = escape(event.get("event_type", "EVENT"))
        summary = escape(strip_hex_text(report.get("summary", "No analysis available.")))
        score = report.get("risk_score", 0.0)
        thesis = escape(strip_hex_text(report.get("thesis", "")))

        lines = [
            f"🐋 <b>Whale Alert</b> — {wallet_label}",
            f"<code>{addr_short}</code>",
            "",
            f"⛓️ <b>Chain:</b> {chain}",
            f"📊 <b>Type:</b> {event_type}",
            f"⚠️ <b>Risk:</b> {self._format_score(score)}",
            "",
            f"📝 <b>What happened:</b> {summary}",
        ]
        if thesis:
            lines.append(f"💡 <b>Thesis:</b> {thesis}")
        lines.append("")
        lines.append(self._disclaimer)
        return "\n".join(lines)

    def format_chat_response(self, report: dict[str, Any]) -> str:
        summary = escape(strip_hex_text(report.get("summary", "I couldn't find enough information to answer that.")))
        evidence = report.get("evidence", [])
        raw_score = report.get("risk_score")
        score = raw_score if raw_score is not None else 0.0

        lines = [
            "🧠 <b>Investigation Result</b>",
            "",
            f"{summary}",
        ]
        if evidence:
            lines.append("")
            lines.append("<b>Evidence:</b>")
            for e in evidence[:5]:
                fact = escape(strip_hex_text(e.get("fact", ""))) if isinstance(e, dict) else escape(strip_hex_text(str(e)))
                source = escape(e.get("source", "on-chain")) if isinstance(e, dict) else "on-chain"
                lines.append(f"• {fact} <i>({source})</i>")
        lines.append("")
        lines.append(f"⚠️ <b>Risk Score:</b> {self._format_score(score)}")
        lines.append("")
        lines.append(self._disclaimer)
        return "\n".join(lines)

    def format_briefing(self, briefing: dict[str, Any]) -> str:
        summary = escape(strip_hex_text(briefing.get("summary", "No briefing available.")))
        events = briefing.get("events", [])

        lines = [
            "📋 <b>Daily Briefing</b>",
            "",
            f"{summary}",
        ]
        if events:
            lines.append("")
            lines.append("<b>Top Events:</b>")
            for e in events[:10]:
                if isinstance(e, dict):
                    lines.append(f"• {escape(strip_hex_text(e.get('summary', str(e))))}")
                else:
                    lines.append(f"• {escape(strip_hex_text(str(e)))}")
        lines.append("")
        lines.append(self._disclaimer)
        return "\n".join(lines)

    def format_channel_post(self, event: dict[str, Any], report: dict[str, Any]) -> str:
        return format_premium_event_post(event, report)

    def _format_score(self, score: float) -> str:
        if score >= 0.7:
            return f"🔴 {score:.0%}"
        if score >= 0.4:
            return f"🟡 {score:.0%}"
        return f"🟢 {score:.0%}"
