from html import escape
from typing import Any


def format_investigation_result(result: dict[str, Any]) -> str:
    summary = escape(str(result.get("summary", "No analysis available.")))
    thesis = escape(str(result.get("thesis", "")))
    raw_score = result.get("risk_score")
    score = raw_score if raw_score is not None else 0.0

    if score > 0.7:
        emoji = "🔴"
    elif score >= 0.3:
        emoji = "🟡"
    else:
        emoji = "🟢"

    lines = [
        "🧠 <b>Summary</b>",
        f"{summary}",
        "",
        "🎯 <b>Thesis</b>",
        f"{thesis}",
        "",
        f"⚠️ <b>Risk Score:</b> {emoji} {score:.0%}",
    ]
    return "\n".join(lines)
