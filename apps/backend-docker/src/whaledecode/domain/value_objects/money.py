from dataclasses import dataclass


@dataclass(frozen=True)
class Money:
    value: float
    currency: str = "USD"

    def __str__(self) -> str:
        if self.value >= 1_000_000:
            return f"${self.value / 1_000_000:.2f}M"
        if self.value >= 1_000:
            return f"${self.value / 1_000:.2f}K"
        return f"${self.value:.2f}"
