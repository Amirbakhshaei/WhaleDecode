from whaledecode.domain.policies.event_weights import EVENT_TYPE_WEIGHTS


async def score_event_node(state: dict) -> dict:
    event = state.get("event_data", {})
    event_type = event.get("event_type", "UNKNOWN")
    weight = EVENT_TYPE_WEIGHTS.get(event_type, 0.1)
    risk_score = state.get("risk_score", 0.0)
    blended = 0.6 * risk_score + 0.4 * weight
    return {"risk_score": round(blended, 2)}
