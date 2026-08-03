from __future__ import annotations

import re
from html import escape
from typing import Any

_MD_CLEANUP = re.compile(r"```(?:json)?|```|\*\*|__|[*_`]")

_MD2_SPECIAL = set("_[]()~`>#+-=|{}.!")


def _strip_md(text: str) -> str:
    """Remove markdown formatting artifacts from LLM output."""
    return _MD_CLEANUP.sub("", text).strip()


def escape_markdown_v2(text: str) -> str:
    """Escape Telegram MarkdownV2 special chars, preserving code spans,
    blockquote prefixes ('>'), bold/italic markers ('*'), and ||spoiler|| tags."""
    out: list[str] = []
    in_code = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "`":
            in_code = not in_code
            out.append(ch)
        elif in_code:
            out.append(ch)
        elif ch == "|" and i + 1 < n and text[i + 1] == "|":
            out.append("||")
            i += 1
        elif ch == ">":
            line_start = i == 0 or text[i - 1] == "\n"
            out.append(">" if line_start else "\\>")
        elif ch == "*":
            out.append(ch)
        elif ch in _MD2_SPECIAL:
            out.append("\\" + ch)
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def format_premium_event_post(event_data: dict[str, Any], analysis: dict[str, Any]) -> str:
    """Minimalist Apple-style channel post."""

    risk = float(analysis.get("risk_score", 0.0))
    if risk >= 0.7:
        risk_ui = "🔴 HIGH"
    elif risk >= 0.4:
        risk_ui = "🟡 MODERATE"
    else:
        risk_ui = "🟢 LOW"

    raw = event_data.get("raw_json", {})
    amount = f"{float(raw.get('amount', 0) or event_data.get('amount', 0)):,.0f}"
    token = raw.get('token', event_data.get('token', 'UNKNOWN'))
    chain = str(event_data.get('chain', 'Unknown')).capitalize()
    value_usd = float(raw.get('value_usd', 0) or event_data.get('value_usd', 0))

    summary = escape(_strip_md(str(analysis.get('summary', 'No summary provided.'))))
    thesis = escape(_strip_md(str(analysis.get('thesis', 'No thesis formulated.'))))

    return f"""✦ <b>WHALEDECODE</b> PRO
<i>On-Chain Event Analysis</i>

<b>ASSET:</b> <code>{amount} {token}</code>
<b>NETWORK:</b> <code>{chain}</code>
<b>VALUE:</b> <code>${value_usd:,.2f}</code>

<b>RISK PROFILE:</b> {risk_ui} <code>({int(risk * 100)}%)</code>

<b>EXECUTIVE SUMMARY</b>
<blockquote>{summary}</blockquote>

<b>INVESTMENT THESIS</b>
<blockquote>{thesis}</blockquote>

—
<code>Intelligence relies on on-chain heuristics. Not financial advice.</code>"""
