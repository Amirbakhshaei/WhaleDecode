STRONG_MODEL_ID = "llama-3.3-70b-versatile"
CHEAP_MODEL_ID = "llama-3.1-8b-instant"

MODEL_PRICING: dict[str, dict[str, float]] = {
    "llama-3.3-70b-versatile": {"input_per_1k": 0.00059, "output_per_1k": 0.00079},
    "llama-3.1-8b-instant": {"input_per_1k": 0.00005, "output_per_1k": 0.00008},
    "gpt-4o": {"input_per_1k": 0.0025, "output_per_1k": 0.01},
    "gpt-4o-mini": {"input_per_1k": 0.00015, "output_per_1k": 0.0006},
}


def get_model_cost(model_id: str, tokens_in: int, tokens_out: int) -> float:
    pricing = MODEL_PRICING.get(model_id)
    if pricing is None:
        return 0.0
    cost_in = (tokens_in / 1000) * pricing["input_per_1k"]
    cost_out = (tokens_out / 1000) * pricing["output_per_1k"]
    return round(cost_in + cost_out, 6)
