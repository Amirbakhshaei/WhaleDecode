"""Pipeline-wide constants and default repository targets."""
from __future__ import annotations

from dataclasses import dataclass

# Chains this pipeline explicitly supports. 0 == cross-EVM (no specific chain).
SUPPORTED_CHAIN_IDS: frozenset[int] = frozenset({1, 42161, 8453, 0})

ETHEREUM = 1
ARBITRUM = 42161
BASE = 8453
CROSS_EVM = 0

# Categories whose label applies to the *same* address across every supported L1/L2
# (e.g. a CEX hot wallet or a deterministic protocol deployer is the same contract
# on each chain). Token/stablecoin addresses differ per chain, so they are NOT replicated.
CROSS_CHAIN_REPLICATE: frozenset[str] = frozenset(
    {"CEX", "Bridge", "Protocol", "DEX", "MEV Bot"}
)

# File extensions we attempt to parse for labels.
LABEL_FILE_SUFFIXES: frozenset[str] = frozenset({".json", ".csv", ".sql", ".yaml", ".yml"})


@dataclass(frozen=True)
class RepoTarget:
    """A GitHub repository to crawl plus an optional ref (branch/tag/sha)."""

    full_name: str  # "owner/repo"
    ref: str | None = None  # default branch if None
    # Glob-style path filters (substring match on the tree path). Empty == anywhere.
    path_includes: tuple[str, ...] = ()


# Default public repositories that publish EVM address labels (GitHub tree crawl).
# DefiLlama/chainlist is intentionally excluded: it's a chain registry (RPC/chainId
# metadata), not an address->label dataset, so it yields 0 label files.
# L2BEAT's canonical contract data lives in .ts configs (unparseable here); the only
# flat address dataset is discovered.json (token symbols) under discover-tokens.
DEFAULT_REPO_TARGETS: tuple[RepoTarget, ...] = (
    RepoTarget("duneanalytics/spellbook", path_includes=("labels", "seeds")),
    RepoTarget("brianleect/etherscan-labels", path_includes=("combined",)),
    RepoTarget("L2BEAT/l2beat", path_includes=("discover-tokens",)),
)

# Token metadata ingested via TokenMetadataService (Uniswap + CoinGecko token lists),
# not from a GitHub repo.
TOKEN_LIST_URLS: tuple[str, ...] = (
    "https://tokens.uniswap.org",
    "https://tokens.coingecko.com/uniswap/all.json",
)

# Multicall3 is deployed at this address on Ethereum, Arbitrum, Base and most EVMs;
# used by TokenMetadataService to batch symbol()/decimals()/name() for missing tokens.
MULTICALL3_ADDRESS = "0xcA11bde05977b3631167028862bE2a173976CA11"
