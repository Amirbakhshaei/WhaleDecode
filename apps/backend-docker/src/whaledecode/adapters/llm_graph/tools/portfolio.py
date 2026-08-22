"""Wallet portfolio telemetry for the chat investigation graph.

Built on standard JSON-RPC only (eth_getBalance / eth_getTransactionCount, and
Multicall3 to batch ``balanceOf`` probes into a single eth_call), so it works
over any provider — dRPC, Infura, etc. — with no proprietary token API.
"""
from typing import Any

from whaledecode.domain.ports.chain_provider import ChainProviderPort

MAX_TOKENS = 5

# High-liquidity tokens probed for a wallet's holdings on each chain.
KNOWN_TOKENS: dict[str, list[str]] = {
    "ETH": [
        "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",  # WETH
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",  # USDC
        "0xdAC17F958D2ee523a2206206994597C13D831ec7",  # USDT
        "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",  # WBTC
        "0x6B175474E89094C44Da98b954EedeAC495271d0F",  # DAI
    ],
    "ARB": [
        "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",  # WETH
        "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",  # USDC
        "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",  # USDT
        "0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f",  # WBTC
        "0x912CE59144191C1204E64559FE8253a0e49E6548",  # ARB
    ],
    "BASE": [
        "0x4200000000000000000000000000000000000006",  # WETH
        "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC
        "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",  # USDT
        "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf",  # cbBTC
        "0x940181a94A35A4569E4529A3CDfB74e38FD98631",  # AERO
    ],
}

_NATIVE_DECIMALS = 18


async def fetch_complete_wallet_profile(
    provider: ChainProviderPort,
    address: str,
    chain: str = "ETH",
) -> dict[str, Any]:
    """Native balance, tx count, and top ERC-20 holdings (symbol + amount) for a wallet.

    Metadata is only resolved for the top non-zero tokens, keeping RPC traffic low.
    """
    chain_key = chain.upper()
    tokens = KNOWN_TOKENS.get(chain_key, KNOWN_TOKENS["ETH"])
    balances = await provider.get_token_balances(chain_key, address, tokens)
    native_hex = await provider.get_balance(chain_key, address)
    tx_count = await provider.get_transaction_count(chain_key, address)

    ranked = [
        (token, wei)
        for token, wei in sorted(balances.items(), key=lambda item: item[1], reverse=True)
        if wei and wei > 0
    ]
    top_tokens = []
    for token, wei in ranked[:MAX_TOKENS]:
        meta = await provider.get_token_metadata(chain_key, token)
        decimals = meta.get("decimals") if isinstance(meta.get("decimals"), int) else 18
        top_tokens.append(
            {
                "symbol": meta.get("symbol") or "UNKNOWN",
                "amount": wei / (10**decimals),
                "contract": token,
            }
        )

    try:
        native_balance = int(native_hex, 16) / (10**_NATIVE_DECIMALS) if native_hex else 0.0
    except (TypeError, ValueError):
        native_balance = 0.0

    return {
        "address": address,
        "chain": chain_key,
        "native_symbol": "ETH",
        "native_balance": native_balance,
        "tx_count": tx_count,
        "tokens": top_tokens,
    }
