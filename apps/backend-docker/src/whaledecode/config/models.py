STRONG_MODEL_ID = "openai/gpt-oss-120b"
CHEAP_MODEL_ID = "openai/gpt-oss-20b"

MODEL_PRICING: dict[str, dict[str, float]] = {
    # Groq pricing per 1M tokens ($0.15 in / $0.60 out), normalized to 1k.
    "openai/gpt-oss-120b": {"input_per_1k": 0.00015, "output_per_1k": 0.0006},
    # $0.075 in / $0.30 out per 1M.
    "openai/gpt-oss-20b": {"input_per_1k": 0.000075, "output_per_1k": 0.0003},
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
