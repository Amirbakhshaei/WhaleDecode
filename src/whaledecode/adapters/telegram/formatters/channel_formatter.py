from __future__ import annotations

import logging
import re
from html import escape
from typing import Any

from whaledecode.adapters.llm_graph.utils import extract_clean_json

logger = logging.getLogger(__name__)


# Neutral phrasing used when the LLM genuinely lacks grounding (it emits "N/A"
# per its own prompt rule) so the channel never prints the literal sentinel.
_NEUTRAL_FALLBACK = {
    "profile": "Entity under analysis.",
    "context": "Market context unavailable.",
    "impact": "Impact under assessment.",
}

# Sentinels the LLM uses for "data missing" — treated as absent, not surfaced.
_MISSING_RE = re.compile(r"^\s*\[?\s*(n/?a|none|null|-|tbd)\s*\]?\s*$", re.IGNORECASE)


def _is_missing(text: Any) -> bool:
    """True when the LLM returned an explicit 'no data' sentinel or nothing."""
    if not text:
        return True
    return bool(_MISSING_RE.match(str(text)))


def parse_synthesis_points(output_json: Any) -> dict[str, str]:
    """Extract concise 1-sentence points from LLM output JSON or raw summary.

    Any "N/A"-style sentinel is normalized to neutral, non-assertive fallback
    text so the channel never echoes the raw token back to traders."""
    if isinstance(output_json, str):
        data = extract_clean_json(output_json)
    else:
        data = output_json or {}

    profile = (
        data.get("entity_profile")
        or data.get("fundamental_flow")
        or data.get("fundamental_summary")
    )
    context = (
        data.get("context")
        or data.get("technical_context")
        or data.get("technical_summary")
    )
    impact = (
        data.get("impact")
        or data.get("institutional_bias")
        or data.get("bias_summary")
    )

    # Fall back to parsing legacy markdown-bullet summary (Action/Context/Bias).
    if not (profile and context and impact) and data.get("summary"):
        parsed = {}
        for line in str(data["summary"]).splitlines():
            match = _SMC_BULLET.search(line)
            if match:
                parsed[match.group(1)] = match.group(2).strip()
        profile = profile or parsed.get("Action")
        context = context or parsed.get("Context")
        impact = impact or parsed.get("Bias")

    def shorten(text: Any, fallback: str) -> str:
        if _is_missing(text):
            return fallback
        first = str(text).split(". ")[0].strip()
        return first + ("." if not first.endswith(".") else "")

    return {
        "profile": _strip_hex(shorten(profile, _NEUTRAL_FALLBACK["profile"])),
        "context": _strip_hex(shorten(context, _NEUTRAL_FALLBACK["context"])),
        "impact": _strip_hex(shorten(impact, _NEUTRAL_FALLBACK["impact"])),
    }


_MD_CLEANUP = re.compile(r"```(?:json)?|```|\*\*|__|[*_`]")

# Deterministic guard: raw EVM hex (20-byte address or 32-byte hash, full or
# abbreviated 0x…abc) must never reach the trader-intelligence lines, even if the
# LLM or a cached legacy run slipped one in. Also removes ||0x…|| spoiler wraps.
_HEX_TOKEN = re.compile(r"0x[0-9a-fA-F]{4,}(?:\.{2,}[0-9a-fA-F]{0,4})?")
_SPOILER_HEX = re.compile(r"\|\|0x[0-9a-fA-F]{4,}(?:\|{2}|[^|]*\|{2})")
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
    summary = escape_markdown_v2(_strip_hex(_strip_md(str(analysis.get("summary", "")))))
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

    summary = escape(_strip_hex(_strip_md(str(analysis.get('summary', 'No summary provided.')))))
    thesis = escape(_strip_hex(_strip_md(str(analysis.get('thesis', 'No thesis formulated.')))))

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


def _strip_hex(text: str) -> str:
    """Remove raw EVM hex tokens (and their spoiler wraps) from a summary line.

    Whitespace is collapsed per line only, so multi-bullet summaries keep
    their line structure."""
    out = _SPOILER_HEX.sub("", text)
    out = _HEX_TOKEN.sub("", out)
    return "\n".join(" ".join(line.split()) for line in out.splitlines()).strip("| ")


strip_hex_text = _strip_hex


def _smc_fields(report: dict[str, Any]) -> tuple[str, str, str]:
    """Extract the three trader-intelligence fields, preferring the structured
    LLM output keys over the legacy markdown-bullet parse. Raw hex is stripped
    deterministically so the channel can never echo an address/hash."""
    fields: dict[str, str] = {}
    for line in str(report.get("summary", "")).splitlines():
        match = _SMC_BULLET.search(line)
        if match:
            fields[match.group(1)] = match.group(2).strip()
    return (
        _strip_hex(str(report.get("fundamental_summary") or fields.get("Action") or report.get("action", ""))),
        _strip_hex(str(report.get("technical_summary") or fields.get("Context") or report.get("context", ""))),
        _strip_hex(str(report.get("bias_summary") or fields.get("Bias") or report.get("bias", ""))),
    )


def build_alert_data(
    event_data: dict[str, Any],
    report: dict[str, Any],
    *,
    bot_username: str = "",
) -> dict[str, Any]:
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
    synthesis = parse_synthesis_points(report)
    return {
        "value_usd": _value_usd(event_data, report),
        "token_amount_formatted": f"{amount:,.0f} {asset}".strip() if amount > 0 else "",
        "asset": asset,
        "chain": chain,
        "action": str(event_data.get("event_type", "TRANSFER")).upper(),
        "score": _risk_percent(risk_score),
        "profile": synthesis["profile"],
        "context": synthesis["context"],
        "impact": synthesis["impact"],
        "risk_score": risk_score,
        "fundamental_summary": action,
        "technical_summary": context,
        "bias_summary": bias,
        "tx_hash": tx_hash,
        "from_address": from_addr,
        "to_address": to_addr,
        "from_label": truncate_hash(from_addr) if from_addr else "Unknown Wallet",
        "to_label": truncate_hash(to_addr) if to_addr else "Unknown Wallet",
        "tx_url": url_for("tx", tx_hash, chain) if tx_hash else "#",
        "from_url": url_for("address", from_addr, chain) if from_addr else "#",
        "to_url": url_for("address", to_addr, chain) if to_addr else "#",
        # Intra-platform actions: deep links back into our own Telegram bot.
        "track_link": deep_link(f"track_{from_addr}", bot_username),
        "analyze_link": deep_link(f"analyze_{tx_hash}", bot_username),
    }


def deep_link(payload: str, bot_username: str = "") -> str:
    """Intra-platform deep link back into our own Telegram bot.

    ``?start=track_<addr>`` / ``?start=analyze_<tx>`` keep users inside the
    WhaleDecode bot instead of leaking them to external platforms.
    """
    bot = bot_username.strip().lstrip("@") or "whaledecodebot"
    return f"https://t.me/{bot}?start={payload}"


def format_alert(alert_data: dict[str, Any]) -> str:
    """Deterministic Template A (L1 Mainnet) or Template B (L2 Velocity) channel alert.

    Renders directly from ``build_alert_data`` output so every section is built from
    structured fields, never from the legacy verbose paragraph body."""
    value_usd = _as_float(alert_data.get("value_usd", 0.0))
    asset = escape(str(alert_data.get("asset", "UNKNOWN")))
    chain = _normalize_chain(alert_data.get("chain", "ETH"))
    action = str(alert_data.get("action", "TRANSFER")).upper()
    score = int(_as_float(alert_data.get("score", 0)))

    profile = escape(str(alert_data.get("profile") or "High-value institutional entity."))
    context = escape(str(alert_data.get("context") or "Off-exchange liquidity positioning."))
    impact = escape(str(alert_data.get("impact") or "Reduces immediate exchange-held supply."))

    from_label = escape(str(alert_data.get("from_label") or "Unknown Wallet"))
    to_label = escape(str(alert_data.get("to_label") or "Unknown Wallet"))
    track_link = escape(str(alert_data.get("track_link") or ""), quote=True)
    analyze_link = escape(str(alert_data.get("analyze_link") or ""), quote=True)

    # Intra-platform actions footer: route users back into our own bot.
    action_line = ""
    if track_link and analyze_link:
        if chain.upper() in ("ETH", "ETHEREUM"):
            action_line = (
                f"👇 <b>WhaleDecode Platform Actions:</b>\n"
                f"🕵️‍♂️ <a href=\"{track_link}\">Track This Entity</a> | "
                f"💬 <a href=\"{analyze_link}\">Ask AI About Tx</a>"
            )
        else:
            action_line = (
                f"👇 <b>WhaleDecode Platform Actions:</b>\n"
                f"⚡ <a href=\"{track_link}\">Auto-Track Wallet</a> | "
                f"💬 <a href=\"{analyze_link}\">Deep Dive Tx</a>"
            )

    # ------------------------------------------------------------------
    # TEMPLATE A: L1 Mainnet (ETH)
    # ------------------------------------------------------------------
    if chain.upper() in ("ETH", "ETHEREUM"):
        return (
            f"🐋 <b>STRATEGIC {action} | {chain}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Total Value:</b> <b>${value_usd:,.2f} USD</b>\n"
            f"🪙 <b>Asset:</b> {asset}\n"
            f"🛣️ <b>Flow:</b> <code>{from_label}</code> ➔ <code>{to_label}</code>\n"
            f"🎯 <b>Conviction Score:</b> {score}/100\n\n"
            f"🧠 <b>Agentic Synthesis:</b>\n"
            f"• <b>Entity:</b> {profile}\n"
            f"• <b>Context:</b> {context}\n"
            f"• <b>Impact:</b> {impact}\n\n"
            f"{action_line}"
        )

    # ------------------------------------------------------------------
    # TEMPLATE B: L2 / High Velocity (BASE, ARB, SOL, ...)
    # ------------------------------------------------------------------
    return (
        f"⚡ <b>SMART MONEY {action} | {chain}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Total Value:</b> <b>${value_usd:,.2f} USD</b>\n"
        f"🪙 <b>Asset:</b> {asset}\n"
        f"🎯 <b>Conviction Score:</b> {score}/100\n\n"
        f"🧠 <b>Agentic Synthesis:</b>\n"
        f"• <b>Profile:</b> {profile}\n"
        f"• <b>Impact:</b> {impact}\n\n"
        f"{action_line}"
    )
