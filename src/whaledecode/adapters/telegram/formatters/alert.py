from typing import Any


def format_alert_message(event: dict[str, Any], report: dict[str, Any]) -> str:
    return (
        f"🚨 *Whale Alert*\n\n"
        f"*Event:* {event.get('event_type', 'UNKNOWN')}\n"
        f"*Chain:* {event.get('chain', '?')}\n"
        f"*Tx:* `{event.get('tx_hash', '?')[:10]}...`\n\n"
        f"*Summary:* {report.get('summary', 'No analysis.')}\n"
        f"*Risk Score:* {report.get('risk_score', 0.0):.2f}\n\n"
        f"{report.get('disclaimer', '')}"
    )
