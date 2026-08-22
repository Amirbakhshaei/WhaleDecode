"""Domain-Driven Ingestion Configuration: per-chain whale floors for SQL-level worker filtering.

`should_ingest_event` is the first-principles ingestion gate — evaluated in O(1)
memory lookup before any DB write, so dust never reaches `candidate_events`.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChainFilterRule:
    chain_name: str
    min_usd_threshold: float
    allowed_categories: frozenset[str]
    allowed_assets: frozenset[str]


CHAIN_RULES: dict[str, ChainFilterRule] = {
    "ETH": ChainFilterRule(
        chain_name="Ethereum",
        min_usd_threshold=250_000.0,  # $250k floor for L1 to destroy noise
        allowed_categories=frozenset({"external", "internal", "erc20"}),
        allowed_assets=frozenset({"ETH", "WETH", "USDT", "USDC", "WBTC"}),
    ),
    "ARB": ChainFilterRule(
        chain_name="Arbitrum",
        min_usd_threshold=50_000.0,  # $50k floor for L2 DeFi
        allowed_categories=frozenset({"external", "erc20"}),
        allowed_assets=frozenset({"ETH", "USDC", "ARB", "GMX"}),
    ),
    "BASE": ChainFilterRule(
        chain_name="Base",
        min_usd_threshold=25_000.0,  # $25k floor to capture retail altcoin velocity
        allowed_categories=frozenset({"external", "erc20"}),
        allowed_assets=frozenset({"ETH", "USDC"}),  # Allow all ERC20s dynamically if USD >= threshold
    ),
}


def should_ingest_event(chain: str, value_usd: float, category: str) -> bool:
    """First-Principles Ingestion Gate.

    Evaluates in O(1) memory lookup to enforce zero-write-amplification.
    """
    rule = CHAIN_RULES.get(chain.upper())
    if not rule:
        return value_usd >= 50_000.0  # Fallback default

    if value_usd < rule.min_usd_threshold:
        return False

    if category not in rule.allowed_categories:
        return False

    return True
