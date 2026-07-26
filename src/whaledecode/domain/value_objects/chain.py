from enum import IntEnum


class Chain(IntEnum):
    ETH = 1
    BASE = 8453
    ARB = 42161

    def label(self) -> str:
        return {1: "Ethereum", 8453: "Base", 42161: "Arbitrum"}[self.value]
