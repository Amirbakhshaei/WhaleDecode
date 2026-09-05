from __future__ import annotations

import logging
import re
from html import escape
from typing import Any

from whaledecode.adapters.llm_graph.formatting.sanitizer import strip_prompt_artifacts
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

# Placeholder / fallback phrases that must NEVER be broadcast to the live channel.
FALLBACK_PHRASES = {
    "entity under analysis",
    "market context unavailable",
    "impact under assessment",
    "unknown context",
    "context unavailable",
}


def is_valid_synthesis(summary_text: str | None) -> bool:
    """Gate broadcast: reject empty / placeholder / partial LLM synthesis.

    Prevents neutral fallback strings (or truncated output) from reaching the
    public channel when synthesis times out or schema parsing partially fails.
    """
    if not summary_text or len(summary_text.strip()) < 40:
        return False
    lowered = summary_text.lower()
    return not any(phrase in lowered for phrase in FALLBACK_PHRASES)


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
    summary = str(analysis.get("summary", ""))
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
            lines.append(f"  • {escape_markdown_v2(_strip_hex(_strip_md(strip_prompt_artifacts(bullet))))}")
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

    summary = escape(_strip_hex(_strip_md(strip_prompt_artifacts(str(analysis.get('summary', 'No summary provided.'))))))
    thesis = escape(_strip_hex(_strip_md(strip_prompt_artifacts(str(analysis.get('thesis', 'No thesis formulated.'))))))

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

    # Edge Intelligence fields: persisted entity columns first, LLM context second.
    def _intel(key: Any, report_key: str = "") -> Any:
        return key if key is not None else (report.get(report_key) if report_key else None)

    coordinated = bool(_intel(event_data.get("coordinated_flag"), "coordinated"))
    conviction_ctx = report.get("conviction") if isinstance(report.get("conviction"), dict) else {}
    pool_impact = _as_float(
        _intel(event_data.get("pool_impact_percentage"), "") or conviction_ctx.get("pool_impact_ratio_pct", 0)
    )
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
        # Edge Intelligence (predictive alpha).
        "win_rate": _opt_float(_intel(event_data.get("win_rate"))),
        "pool_impact_percentage": pool_impact,
        "cluster_origin": _intel(event_data.get("cluster_origin"), "funding_attribution"),
        "hop_count": int(_as_float(_intel(event_data.get("hop_count")))),
        "coordinated_flag": coordinated,
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


def _opt_float(value: Any) -> float | None:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed


def deep_link(payload: str, bot_username: str = "") -> str:
    """Intra-platform deep link back into our own Telegram bot.

    ``?start=track_<addr>`` / ``?start=analyze_<tx>`` keep users inside the
    WhaleDecode bot instead of leaking them to external platforms.
    """
    bot = bot_username.strip().lstrip("@") or "whaledecodebot"
    return f"https://t.me/{bot}?start={payload}"


def format_syndicate_dossier(
    event_data: dict[str, Any],
    report: dict[str, Any],
    *,
    bot_username: str = "",
) -> str:
    """Syndicate Dossier format: viral, structured intelligence brief for channel.

    Template:
    🕵️ *WHALEDECODE | SYNDICATE ACCUMULATION*

    *Asset:* `${token_symbol}` on *{chain}*
    *Total Coordinated Volume:* `${total_usd}` ({wallets_count} Wallets)
    *Action:* Aggressive Market Accumulation

    🧩 *Cluster Graph Forensics:*
    • *Parent Funding:* `{parent_label}` ({funding_time_ago})
    • *Execution:* Coordinated across {block_span} blocks
    • *Syndicate Type:* `{cluster_type}`

    📈 *Market Structure (SMC):*
    • *Regime:* `{smc_regime}`
    • *Location:* `{discount_status}` ({ote_status})
    • *Invalidation Floor:* `${invalidation_price}`

    📊 *Entity Profile:*
    • *Cluster Win-Rate:* `{cluster_win_rate}%`
    • *Average Hold Duration:* `{avg_hold_duration}`

    🔗 [DexScreener]({dex_url}) | [BlockExplorer]({explorer_url})
    """
    from whaledecode.adapters.pricing.oracle import SMCAnalysisResult

    raw = event_data.get("raw_json") if isinstance(event_data.get("raw_json"), dict) else {}
    tx_hash = str(event_data.get("tx_hash", ""))
    asset = str(
        raw.get("token") or raw.get("asset") or event_data.get("token") or event_data.get("asset") or "UNKNOWN"
    )
    chain = str(event_data.get("chain", "")).capitalize()
    value_usd = _as_float(raw.get("value_usd", 0) or event_data.get("value_usd", 0))

    # Syndicate / cluster fields
    cluster_wallets = int(_as_float(raw.get("cluster_wallets_count") or event_data.get("cluster_wallets_count") or 1))
    cluster_type = str(raw.get("cluster_type") or event_data.get("cluster_type") or "FRESH_CEX_ACCUMULATOR")
    cluster_origin = str(raw.get("cluster_origin") or raw.get("funding_attribution") or event_data.get("cluster_origin") or "Unknown")
    cluster_win_rate = _as_float(raw.get("win_rate") or event_data.get("win_rate") or 0)
    avg_hold_duration = str(raw.get("avg_hold_duration") or event_data.get("avg_hold_duration") or "N/A")
    block_span = str(raw.get("block_span") or "N/A")
    funding_time_ago = "recent"  # Would compute from timestamps in production

    # SMC analysis from report or event data
    smc_analysis = report.get("smc_analysis") if isinstance(report.get("smc_analysis"), SMCAnalysisResult) else None
    if smc_analysis is None:
        smc_raw = report.get("smc_analysis") if isinstance(report.get("smc_analysis"), dict) else event_data.get("smc_analysis")
        if isinstance(smc_raw, dict):
            # Convert dict to SMCAnalysisResult-like object for formatting
            class _SMCProxy:
                def __init__(self, d):
                    self.__dict__.update(d)
            smc_analysis = _SMCProxy(smc_raw)

    # Format SMC fields
    if smc_analysis:
        smc_regime = str(getattr(smc_analysis, "market_regime", "UNKNOWN"))
        is_discount = bool(getattr(smc_analysis, "is_discount_zone", False))
        ote_confluence = bool(getattr(smc_analysis, "ote_confluence", False))
        invalidation_level = _as_float(getattr(smc_analysis, "invalidation_level", 0))
        discount_status = "Discount Zone" if is_discount else "Premium Zone"
        ote_status = "OTE Confluence ✅" if ote_confluence else "Outside OTE"
        invalidation_price = f"${invalidation_level:,.4f}" if invalidation_level > 0 else "N/A"
    else:
        smc_regime = "UNKNOWN"
        discount_status = "Unknown"
        ote_status = "Unknown"
        invalidation_price = "N/A"

    # URLs
    dex_url = f"https://dexscreener.com/{chain.lower()}/{raw.get('address', '')}" if raw.get("address") else "#"
    explorer_base = {"ethereum": "https://etherscan.io", "base": "https://basescan.org", "arbitrum": "https://arbiscan.io"}.get(chain.lower(), "https://etherscan.io")
    explorer_url = f"{explorer_base}/tx/{tx_hash}" if tx_hash else "#"

    lines = [
        "🕵️ <b>WHALEDECODE | SYNDICATE ACCUMULATION</b>",
        "",
        f"*Asset:* `${asset}` on *{chain}*",
        f"*Total Coordinated Volume:* `${value_usd:,.2f}` ({cluster_wallets} Wallets)",
        "*Action:* Aggressive Market Accumulation",
        "",
        "🧩 <b>Cluster Graph Forensics:</b>",
        f"• <b>Parent Funding:</b> {escape(cluster_origin)} ({funding_time_ago})",
        f"• <b>Execution:</b> Coordinated across {block_span} blocks",
        f"• <b>Syndicate Type:</b> {cluster_type}",
        "",
        "📈 <b>Market Structure (SMC):</b>",
        f"• <b>Regime:</b> {smc_regime}",
        f"• <b>Location:</b> {discount_status} ({ote_status})",
        f"• <b>Invalidation Floor:</b> {invalidation_price}",
        "",
        "📊 <b>Entity Profile:</b>",
        f"• <b>Cluster Win-Rate:</b> {cluster_win_rate:.1f}%" if cluster_win_rate > 0 else "• <b>Cluster Win-Rate:</b> N/A",
        f"• <b>Average Hold Duration:</b> {escape(avg_hold_duration)}",
        "",
        f"🔗 <a href=\"{dex_url}\">DexScreener</a> | <a href=\"{explorer_url}\">BlockExplorer</a>",
    ]

    return "\n".join(lines)


def format_alert(alert_data: dict[str, Any]) -> str:
    """Alpha-first channel alert: predictive intelligence over description.

    Deterministic conditional rendering from ``build_alert_data`` output:
      * coordinated_flag -> 🔥 header; else 🐋 strategic-transfer header
      * pool_impact_percentage >= 1.5% -> ⚠️ liquidity-absorption warning
      * hop_count > 0 -> 🕸️ funding-cluster line
      * Entity/Context/Impact bullets replaced by 🧠 Predictive Intelligence
        (win rate + pool impact). All in-body links removed — actions live
        exclusively in the parameterized inline keyboard.
    """
    value_usd = _as_float(alert_data.get("value_usd", 0.0))
    asset = escape(str(alert_data.get("asset", "UNKNOWN")))
    chain = _normalize_chain(alert_data.get("chain", "ETH"))
    action = str(alert_data.get("action", "TRANSFER")).upper()
    score = int(_as_float(alert_data.get("score", 0)))

    coordinated = bool(alert_data.get("coordinated_flag"))
    pool_impact = _as_float(alert_data.get("pool_impact_percentage"))
    win_rate = alert_data.get("win_rate")
    cluster_origin = str(alert_data.get("cluster_origin") or "")
    hop_count = int(_as_float(alert_data.get("hop_count")))

    if coordinated:
        header = f"🔥 <b>COORDINATED ACCUMULATION | {chain}</b>"
    else:
        header = f"🐋 <b>STRATEGIC {action} | {chain}</b>"

    volume_warning = " ⚠️" if pool_impact >= 1.5 else ""

    lines: list[str] = [
        header,
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"💰 <b>Total Value:</b> <b>${value_usd:,.2f} USD</b>{volume_warning}",
        f"🪙 <b>Asset:</b> {asset}",
        f"🎯 <b>Conviction Score:</b> {score}/100",
    ]

    # Module 2 alpha: obscured institutional money leaves a funding trail.
    if hop_count > 0 and cluster_origin:
        lines.append(
            f"🕸️ <b>Cluster Origin:</b> Funded by {escape(cluster_origin)} ({hop_count} hops)"
        )

    # Predictive intelligence replaces the descriptive synthesis bullets.
    lines.append("")
    lines.append("🧠 <b>Predictive Intelligence:</b>")
    if win_rate is not None and win_rate > 0:
        win_pct = round(win_rate * 100)
        verdict = "high-conviction operator" if win_pct >= 60 else "mixed performer"
        lines.append(f"• <b>Win Rate:</b> {win_pct}% of tracked accumulations profitable (90d) — {verdict}")
    else:
        lines.append("• <b>Win Rate:</b> Untracked wallet — baseline confidence")
    if pool_impact > 0:
        flag = " — anomalous absorption" if pool_impact >= 1.5 else ""
        lines.append(f"• <b>Pool Impact:</b> absorbed {pool_impact:g}% of DEX liquidity{flag}")
    else:
        lines.append("• <b>Pool Impact:</b> below anomaly threshold")

    return "\n".join(lines) + "\n"
