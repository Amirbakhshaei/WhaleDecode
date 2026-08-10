from __future__ import annotations

import re
from html import escape
from typing import Any

_MD_CLEANUP = re.compile(r"```(?:json)?|```|\*\*|__|[*_`]")

_MD2_SPECIAL = set("_[]()~`>#+-=|{}.!")

_EXPLORERS: dict[str, str] = {
    "ethereum": "https://etherscan.io",
    "arbitrum": "https://arbiscan.io",
    "base": "https://basescan.org",
    "bsc": "https://bscscan.com",
}

_CHAIN_BY_ID: dict[int, str] = {1: "Ethereum", 8453: "Base", 42161: "Arbitrum"}

_CHAIN_BY_LABEL: dict[str, str] = {
    "ethereum": "Ethereum",
    "eth": "Ethereum",
    "base": "Base",
    "arbitrum": "Arbitrum",
    "arb": "Arbitrum",
    "bsc": "BSC",
    "bnb": "BSC",
}

_SMC_BULLET = re.compile(r"\*\*(Action|Context|Bias):\s*\*+\s*(.+)$")


def truncate_hash(tag: str) -> str:
    """Collapse a 0x hash/address to ``0x1234…abcd`` for a compact trace line."""
    tag = str(tag)
    if len(tag) <= 12:
        return tag
    return f"{tag[:6]}…{tag[-4:]}"


def url_for(kind: str, tag: str, chain: str) -> str:
    """Explorer URL for an address or transaction on the given chain."""
    base = _EXPLORERS.get(str(chain).strip().lower(), "https://etherscan.io")
    if kind == "tx":
        return f"{base}/tx/{tag}"
    return f"{base}/address/{tag}"


def md_link(label: str, url: str) -> str:
    """MarkdownV2 inline link. ``label`` is a truncated hash (no MD2 specials),
    ``url`` is a plain URL (no MD2 specials), so the entity needs no escaping."""
    return f"[{label}]({url})"


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


def _risk_badge(risk: float) -> str:
    if risk >= 0.7:
        return "🔴 HIGH"
    if risk >= 0.4:
        return "🟡 MODERATE"
    return "🟢 LOW"


def _asset(event_data: dict[str, Any]) -> tuple[str, str]:
    raw = event_data.get("raw_json", {})
    token = raw.get("token") or event_data.get("token") or "UNKNOWN"
    amount = float(raw.get("amount", 0) or event_data.get("amount", 0))
    return f"{amount:,.0f}", str(token)


def _value_usd(event_data: dict[str, Any], analysis: dict[str, Any]) -> float:
    raw = event_data.get("raw_json", {})
    return float(raw.get("value_usd", 0) or event_data.get("value_usd", 0) or analysis.get("value_usd", 0))


def _trace_addresses(event_data: dict[str, Any]) -> tuple[str, str]:
    """Best-effort From/To extraction from raw_json (topics may be nested)."""
    raw = event_data.get("raw_json", {})
    fr = raw.get("from") or event_data.get("from") or ""
    to = raw.get("to") or event_data.get("to") or ""
    return str(fr), str(to)


def format_channel_post_markdown(
    event_data: dict[str, Any],
    analysis: dict[str, Any],
    chain: str = "",
) -> str:
    """High-signal MarkdownV2 channel post: compact hyperlinked trace + SMC focus.

    Builds every section deterministically from ``event_data``/``analysis`` so the
    intelligence summary drives the read, raw hashes become clickable one-liners.
    """
    chain = chain or str(event_data.get("chain", "Unknown"))
    risk = float(analysis.get("risk_score", 0.0))
    summary = escape_markdown_v2(_strip_md(str(analysis.get("summary", ""))))
    event_type = str(event_data.get("event_type", "EVENT")).upper()
    amount, token = _asset(event_data)
    value = _value_usd(event_data, analysis)
    tx = str(event_data.get("tx_hash", ""))
    fr, to = _trace_addresses(event_data)

    lines: list[str] = [
        f"✦ *WHALEDECODE* — {event_type}",
        f"💎 *{amount} {token}* · {chain.capitalize()}",
        f"💰 `${value:,.2f}` · 🎯 *{_risk_badge(risk)}* ({int(risk * 100)}%)",
        "",
    ]

    if summary:
        lines.append("🧠 *SMC Intelligence*")
        for bullet in [s.strip() for s in summary.splitlines() if s.strip()]:
            lines.append(f"  • {bullet}")
        lines.append("")

    trace_parts = []
    if fr:
        trace_parts.append(md_link(truncate_hash(fr), url_for("address", fr, chain)))
    if to:
        trace_parts.append("➔ " + md_link(truncate_hash(to), url_for("address", to, chain)))
    if tx:
        trace_parts.append("| " + md_link(truncate_hash(tx), url_for("tx", tx, chain)))
    if trace_parts:
        lines.append("🔗 *Trace:* " + " ".join(trace_parts))

    return "\n".join(lines)


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


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize_chain(chain: Any) -> str:
    """Map numeric Chain IDs / labels to readable names; fallback to raw."""
    if isinstance(chain, int) or (isinstance(chain, str) and chain.isdigit()):
        return _CHAIN_BY_ID.get(int(chain), str(chain))
    label = str(chain).strip().lower()
    if label in _CHAIN_BY_LABEL:
        return _CHAIN_BY_LABEL[label]
    return str(chain).strip().capitalize() or "Unknown"


def _risk_percent(risk: Any) -> int:
    """Risk score (0–1 float, or 0–100) as an integer percentage."""
    value = _as_float(risk)
    return int(round(value)) if value > 1 else int(round(value * 100))


def _smc_fields(report: dict[str, Any]) -> tuple[str, str, str]:
    """Extract Action/Context/Bias from the report summary bullets or top-level keys."""
    fields: dict[str, str] = {}
    for line in str(report.get("summary", "")).splitlines():
        match = _SMC_BULLET.search(line)
        if match:
            fields[match.group(1)] = match.group(2).strip()
    return (
        fields.get("Action") or str(report.get("action", "")),
        fields.get("Context") or str(report.get("context", "")),
        fields.get("Bias") or str(report.get("bias", "")),
    )


def build_alert_data(event_data: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """Shape a candidate event + LLM report into the alert_data dict ``format_alert`` renders."""
    raw = event_data.get("raw_json") if isinstance(event_data.get("raw_json"), dict) else {}
    tx_hash = str(event_data.get("tx_hash", ""))
    from_addr = str(raw.get("from") or raw.get("fromAddress") or event_data.get("from") or "")
    to_addr = str(raw.get("to") or raw.get("toAddress") or event_data.get("to") or "")
    asset = str(
        raw.get("token") or raw.get("asset") or event_data.get("token") or event_data.get("asset") or "UNKNOWN"
    )
    chain = str(event_data.get("chain", ""))
    amount = _as_float(raw.get("amount") or event_data.get("amount"))
    action, context, bias = _smc_fields(report)
    risk_score = report.get("risk_score", 0.0)
    return {
        "value_usd": _value_usd(event_data, report),
        "token_amount_formatted": f"{amount:,.0f} {asset}".strip() if amount > 0 else "",
        "asset": asset,
        "chain": chain,
        "score": _risk_percent(risk_score),
        "risk_score": risk_score,
        "fundamental_summary": action or "N/A",
        "technical_summary": context or "N/A",
        "bias_summary": bias or "Neutral",
        "tx_hash": tx_hash,
        "from_address": from_addr,
        "to_address": to_addr,
        "from_label": truncate_hash(from_addr) if from_addr else "Unknown Wallet",
        "to_label": truncate_hash(to_addr) if to_addr else "Unknown Wallet",
        "tx_url": url_for("tx", tx_hash, chain) if tx_hash else "#",
        "from_url": url_for("address", from_addr, chain) if from_addr else "#",
        "to_url": url_for("address", to_addr, chain) if to_addr else "#",
    }


def format_alert(alert_data: dict[str, Any]) -> str:
    """Institutional-trader channel alert: high-density HTML. One-line micro anchors
    hold the trace links; the expandable blockquote hides ONLY the raw hash data,
    never the trader-intelligence text."""
    value_usd = _as_float(alert_data.get("value_usd", 0.0))
    asset = escape(str(alert_data.get("asset", "UNKNOWN")))
    chain = _normalize_chain(alert_data.get("chain", "ETH"))
    score = int(_as_float(alert_data.get("score", 0)))
    token_amount = escape(str(alert_data.get("token_amount_formatted", "")))

    fundamental = escape(str(alert_data.get("fundamental_summary") or "N/A"))
    technical = escape(str(alert_data.get("technical_summary") or "N/A"))
    bias = escape(str(alert_data.get("bias_summary") or "Neutral"))

    tx_url = escape(str(alert_data.get("tx_url") or "#"), quote=True)
    from_url = escape(str(alert_data.get("from_url") or "#"), quote=True)
    to_url = escape(str(alert_data.get("to_url") or "#"), quote=True)
    from_label = escape(str(alert_data.get("from_label") or "Unknown Wallet"))
    to_label = escape(str(alert_data.get("to_label") or "Unknown Wallet"))

    value_line = f"💰 <b>Value:</b> ${value_usd:,.2f}"
    if token_amount:
        value_line += f" ({token_amount})"

    return f"""🚨 <b>WHALE ALERT</b> | <b>{asset}</b>
───────────────────────────
{value_line}
🌐 <b>Chain:</b> {chain} | 🎯 <b>Score:</b> {score}/100

🧠 <b>TRADER INTELLIGENCE</b>
• <b>Fundamental Flow:</b> {fundamental}
• <b>Technical Context:</b> {technical}
• <b>Institutional Bias:</b> {bias}

<blockquote expandable>🔗 <a href="{tx_url}">Tx</a> | <a href="{from_url}">{from_label}</a> ➔ <a href="{to_url}">{to_label}</a></blockquote>""".strip()
