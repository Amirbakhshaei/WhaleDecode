

async def format_briefing_node(state: dict) -> dict:
    summary = state.get("summary", "No analysis.")
    evidence = state.get("evidence", [])
    thesis = state.get("thesis", "")
    risk = state.get("risk_score", 0.0)
    disclaimer = state.get("disclaimer", "")

    evidence_lines = "\n".join(f"- {e.get('fact', '')}" for e in evidence[:5])

    formatted = (
        f"**Investigation Report**\n\n"
        f"{summary}\n\n"
        f"**Risk Score:** {risk:.2f}\n"
        f"**Thesis:** {thesis}\n\n"
        f"**Evidence:**\n{evidence_lines}\n\n"
        f"---\n{disclaimer}"
    )
    return {"summary": formatted}
