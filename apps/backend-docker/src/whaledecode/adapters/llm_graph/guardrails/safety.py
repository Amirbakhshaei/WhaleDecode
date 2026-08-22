DISCLAIMER = "Not financial advice. On-chain data only. Always DYOR."


async def safety_guardrail(state: dict) -> dict:
    state["disclaimer"] = DISCLAIMER
    if state.get("risk_score", 0) > 0.95:
        state["disclaimer"] += " HIGH RISK: This event involves significant uncertainty."
    return state
