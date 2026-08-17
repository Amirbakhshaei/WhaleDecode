"""Prune toxic / high-frequency addresses from configured Alchemy webhooks.

Identifies blacklisted addresses (token contracts, DEX routers, CEX hot
sweepers) currently registered on the per-chain webhooks and removes them via
the Notify API's ``update-webhook-addresses`` PATCH.

Run directly:   python -m whaledecode.cli.prune_alchemy_webhooks
Or via CLI:     whaledecode prune-alchemy-webhooks
"""
from __future__ import annotations

import asyncio
import logging

from whaledecode.adapters.alchemy.webhook_manager import AlchemyWebhookManager
from whaledecode.config.logging import setup_logging
from whaledecode.config.settings import Settings

log = logging.getLogger(__name__)

# Hard blacklist: never monitor token contracts, DEX routers, or CEX hot
# liquidity sweepers via webhooks — they generate firehose deliveries that burn
# CUs (0.04 CU/byte) without producing actionable whale moves.
BLACKLISTED_ADDRESSES: set[str] = {
    # Common ERC-20 Token Contracts (global transfer firehoses)
    "0xdac17f958d2ee523a2206206994597c13d831ec7",  # USDT (Ethereum)
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",  # USDC (Ethereum)
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",  # WETH (Ethereum)
    "0xaf88d065e77c8cc2239327c5edb3a432268e5831",  # USDC (Arbitrum)
    "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9",  # USDT (Arbitrum)
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",  # USDC (Base)
    "0x4200000000000000000000000000000000000006",  # WETH (Base)
    # High-Frequency DEX Aggregator & Router Contracts
    "0x1111111254eeb25477b68fb85ed929f73a960582",  # 1inch v5 Router
    "0x111111125421ca6dc452d289314280a0f8842a65",  # 1inch v6 Router
    "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad",  # Uniswap Universal Router
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45",  # Uniswap SwapRouter02
    "0xe592427a0aece92de3edee1f18e0157c05861564",  # Uniswap v3 SwapRouter
    "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f",  # SushiSwap Router
    # High-Frequency CEX Sweepers (100k+ txs/day)
    "0x28c6c06298d514db089934071355e5743bf21d60",  # Binance Hot Wallet 14
    "0x21a31ee1afc51d94c2efccaa2092ad1028285549",  # Binance Hot Wallet 15
}


async def run_pruner() -> int:
    settings = Settings()
    setup_logging(settings)

    manager = AlchemyWebhookManager.from_settings(settings)
    if not manager.auth_token:
        log.error("prune_no_token", extra={"hint": "ALCHEMY_NOTIFY_TOKEN / ALCHEMY_AUTH_TOKEN not set"})
        return 1

    removed_total = 0
    for chain, webhook_id in manager.webhook_ids.items():
        if not webhook_id:
            log.warning("prune_skip_chain", extra={"chain": chain, "hint": "no ALCHEMY_WEBHOOK_ID configured"})
            continue

        registered = await manager.list_addresses(webhook_id)
        log.info(
            "prune_listed",
            extra={"chain": chain, "webhook_id": webhook_id, "registered": len(registered)},
        )
        flagged = sorted(set(registered) & BLACKLISTED_ADDRESSES)
        if not flagged:
            log.info("prune_clean", extra={"chain": chain})
            continue

        log.warning(
            "prune_flagged",
            extra={"chain": chain, "count": len(flagged), "addresses": flagged},
        )
        if await manager.remove_addresses(webhook_id, flagged):
            removed_total += len(flagged)

    log.info("prune_done", extra={"removed": removed_total})
    return 0


def main() -> int:
    return asyncio.run(run_pruner())


if __name__ == "__main__":
    raise SystemExit(main())
