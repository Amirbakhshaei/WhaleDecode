from __future__ import annotations

from html import escape
from typing import Any


def format_premium_event_post(event_data: dict[str, Any], analysis: dict[str, Any]) -> str:
    """Minimalist 'Apple Pro' channel post using <blockquote> and <code>."""

    # 1. Risk UI
    risk = float(analysis.get("risk_score", 0.0))
    if risk >= 0.7:
        risk_ui = "🔴 <b>HIGH</b>"
    elif risk >= 0.4:
        risk_ui = "🟡 <b>MODERATE</b>"
    else:
        risk_ui = "🟢 <b>LOW</b>"
    risk_pct = int(risk * 100)

    # 2. Extract data safely — walk raw_json fallbacks for token/amount/value
    raw = event_data.get("raw_json", {})
    amount = f"{float(raw.get('amount', 0) or event_data.get('amount', 0)):,.0f}"
    token = raw.get("token", event_data.get("token", "UNKNOWN"))
    chain = str(event_data.get("chain", "Unknown")).capitalize()
    value_usd = float(raw.get("value_usd", 0) or event_data.get("value_usd", 0))
    tx_hash = event_data.get("tx_hash", "")

    summary = escape(str(analysis.get("summary", "No summary provided.")))
    thesis = escape(str(analysis.get("thesis", "No thesis formulated.")))

    # 3. Evidence block
    evidence = analysis.get("evidence", [])
    evidence_lines = ""
    if evidence:
        items = []
        for e in evidence[:5]:
            if isinstance(e, dict):
                fact = escape(e.get("fact", ""))
                src = escape(e.get("source", "on-chain"))
                items.append(f"• {fact} <i>({src})</i>")
            else:
                items.append(f"• {escape(str(e))}")
        evidence_lines = "\n".join(items)

    # 4. Explorer link (best-effort chain detection)
    explorer = "https://etherscan.io/tx/" if chain.lower() == "ethereum" else "#"

    html = f"""✦ <b>WHALEDECODE</b> PRO
<i>On-Chain Event Analysis</i>

<b>ASSET:</b> <code>{amount} {token}</code>
<b>NETWORK:</b> <code>{chain}</code>
<b>VALUE:</b> <code>${value_usd:,.2f}</code>

<b>RISK PROFILE:</b> {risk_ui} <code>({risk_pct}%)</code>

<b>EXECUTIVE SUMMARY</b>
<blockquote>{summary}</blockquote>

<b>INVESTMENT THESIS</b>
<blockquote>{thesis}</blockquote>"""

    if evidence_lines:
        html += f"""

<b>EVIDENCE</b>
<blockquote>{evidence_lines}</blockquote>"""

    html += f"""

—
<i><a href="{explorer}{tx_hash}">View Transaction on Explorer ↗</a></i>
<code>Intelligence relies on on-chain heuristics. Not financial advice.</code>"""

    return html
