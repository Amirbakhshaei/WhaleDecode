"""The two data-gathering tools available to the low-RPM graph's gatherer node.

Deterministic by construction: the gatherer node decides which tool to call from
the raw_event fields; the LLM never routes. Both tools degrade to a readable
string on any data-source failure so the analyst always has context to work from.
"""
from __future__ import annotations

from typing import Any

import httpx
from langchain_core.tools import BaseTool, tool

from whaledecode.domain.ports.chain_provider import ChainProviderPort

DEXSCREENER_API = "https://api.dexscreener.com/latest/dex/tokens/{address}"

DEXSCREENER_CHAIN_ID: dict[str, str] = {
    "ETH": "ethereum",
    "ARB": "arbitrum",
    "BASE": "base",
}

UNAVAILABLE = "Data unavailable"


def create_data_gatherer_tools(
    provider: ChainProviderPort,
    http_client: httpx.AsyncClient | None = None,
) -> list[BaseTool]:
    client = http_client or httpx.AsyncClient(timeout=10)

    @tool
    async def etherscan_tool(tx_hash: str, chain: str = "ETH") -> str:
        """Fetch on-chain facts for a transaction: value flow, involved addresses, balances and account age."""
        try:
            trace = await provider.trace_call(chain, tx_hash)
            from_addr = trace.get("from") or "N/A"
            to_addr = trace.get("to") or "N/A"
            value = trace.get("value") or "0x0"
            balance = await provider.get_balance(chain, from_addr)
            from_tx_count = await provider.get_transaction_count(chain, from_addr)
            return (
                f"tx={tx_hash} on {chain}: value={_wei_to_eth(value)} ETH, "
                f"from={from_addr} (balance={_wei_to_eth(balance)} ETH, tx_count={from_tx_count}), "
                f"to={to_addr}"
            )
        except Exception as exc:
            return f"{UNAVAILABLE} — etherscan lookup failed for {tx_hash}: {exc}"

    @tool
    async def dexscreener_tool(token_address: str, chain: str = "ETH") -> str:
        """Fetch DEX market data for a token: price USD, liquidity, and 24h volume."""
        chain_id = DEXSCREENER_CHAIN_ID.get(chain.upper(), chain.lower())
        try:
            resp = await client.get(DEXSCREENER_API.format(address=token_address))
            resp.raise_for_status()
            pairs = resp.json().get("pairs") or []
            for pair in pairs:
                if pair.get("chainId") != chain_id:
                    continue
                return (
                    f"token={token_address} on {chain}: "
                    f"price=${pair.get('priceUsd') or UNAVAILABLE}, "
                    f"liquidity=${_num(pair.get('liquidity')) or UNAVAILABLE}, "
                    f"volume_24h=${_num(pair.get('volume')) or UNAVAILABLE}, "
                    f"pair={pair.get('pairAddress') or UNAVAILABLE}"
                )
            return f"{UNAVAILABLE} — no {chain} pair found for {token_address}"
        except Exception as exc:
            return f"{UNAVAILABLE} — dexscreener lookup failed for {token_address}: {exc}"

    return [etherscan_tool, dexscreener_tool]


def _wei_to_eth(hex_value: str) -> str:
    try:
        return f"{int(hex_value, 16) / 10**18:.6f}"
    except (ValueError, TypeError):
        return "N/A"


def _num(value: Any) -> str:
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return ""
