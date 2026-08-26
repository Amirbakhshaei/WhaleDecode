from enum import Enum


class Chain(str, Enum):
    """str-enum so ``chain.lower()`` works anywhere a Chain is passed as text."""

    ETH = "ETH"
    BASE = "BASE"
    ARB = "ARB"

    def label(self) -> str:
        return {self.ETH: "Ethereum", self.BASE: "Base", self.ARB: "Arbitrum"}[self]
