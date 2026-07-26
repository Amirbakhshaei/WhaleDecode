from dataclasses import dataclass


@dataclass
class ModelConfig:
    cheap_id: str
    strong_id: str
    cheap_cost_per_1k_in: float = 0.0001
    cheap_cost_per_1k_out: float = 0.0004
    strong_cost_per_1k_in: float = 0.0005
    strong_cost_per_1k_out: float = 0.0015


DEFAULT_MODEL_CONFIG = ModelConfig(
    cheap_id="llama-3.1-8b-instant",
    strong_id="llama-3.3-70b-versatile",
)
