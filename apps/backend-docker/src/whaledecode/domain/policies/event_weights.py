"""Event type weights — agents.md §7.2."""

EVENT_TYPE_WEIGHTS: dict[str, float] = {
    "LARGE_STABLECOIN_TRANSFER": 0.8,
    "NEW_TOKEN_DEPLOYMENT": 0.85,
    "WHALE_ACCUMULATION": 0.75,
    "EXCHANGE_WITHDRAWAL": 0.7,
    "MEV": 0.4,
    "ROUTINE_TRANSFER": 0.2,
    "DUST_SPAM": 0.05,
    "SWAP": 0.35,
    "APPROVE": 0.15,
    "CONTRACT_INTERACTION": 0.3,
    "UNKNOWN": 0.1,
}
