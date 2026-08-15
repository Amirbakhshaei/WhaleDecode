import json
from typing import Any

from cachetools import TTLCache
from langchain_core.tools import tool
from whaledecode.adapters.chain.providers.http_rpc import RateLimitError
from whaledecode.adapters.llm_graph.tools.portfolio import fetch_complete_wallet_profile
from whaledecode.domain.ports.chain_provider import ChainProviderPort

CACHE_SIZE = 1000
CACHE_TTL_SECONDS = 900

RATE_LIMIT_MSG = "Rate limit reached. Proceed with existing context."


def create_onchain_tools(provider: ChainProviderPort) -> list:
    # Bind the provider via closures so each graph gets its own tool instances.
    # Defensive caching: dedupe identical queries within TTL so we never burn
    # RPM on the same address twice. Only successful results are cached —
    # errors pass through so a transient RPC failure isn't frozen for 5 min.
    cache: TTLCache[tuple, str] = TTLCache(maxsize=CACHE_SIZE, ttl=CACHE_TTL_SECONDS)

    def _cache_key(tool_name: str, kwargs: dict) -> tuple:
        args = (kwargs.get("address") or kwargs.get("token_address") or kwargs.get("tx_hash"), kwargs.get("chain", "ETH"))
        return (tool_name, *args)

    async def get_wallet_info(address: str, chain: str = "ETH") -> str:
        """Get basic info about a wallet: ETH balance and total transaction count."""
        key = _cache_key("get_wallet_info", {"address": address, "chain": chain})
        if key in cache:
            return cache[key]
        try:
            balance = await provider.get_balance(chain, address)
            tx_count = await provider.get_transaction_count(chain, address)
            result = f"Wallet {address} on {chain}: balance={_wei_to_eth(balance)} ETH, tx_count={tx_count}"
        except RateLimitError:
            return RATE_LIMIT_MSG
        except Exception as exc:
            return f"ERROR: could not fetch wallet info for {address} on {chain}: {exc}"
        cache[key] = result
        return result

    async def get_token_info(token_address: str, chain: str = "ETH") -> str:
        """Get token metadata: name, symbol, decimals."""
        key = _cache_key("get_token_info", {"token_address": token_address, "chain": chain})
        if key in cache:
            return cache[key]
        try:
            meta = await provider.get_token_metadata(chain, token_address)
            result = (
                f"Token {token_address} on {chain}: name={meta.get('name')}, "
                f"symbol={meta.get('symbol')}, decimals={meta.get('decimals')}"
            )
        except RateLimitError:
            return RATE_LIMIT_MSG
        except Exception as exc:
            return f"ERROR: could not fetch token info for {token_address} on {chain}: {exc}"
        cache[key] = result
        return result

    async def trace_transaction(tx_hash: str, chain: str = "ETH") -> str:
        """Trace a transaction to see internal calls and value flow."""
        key = _cache_key("trace_transaction", {"tx_hash": tx_hash, "chain": chain})
        if key in cache:
            return cache[key]
        try:
            trace = await provider.trace_call(chain, tx_hash)
            result = f"Tx {tx_hash} on {chain}: {_format_trace(trace)}"
        except RateLimitError:
            return RATE_LIMIT_MSG
        except Exception as exc:
            return f"ERROR: could not trace {tx_hash} on {chain}: {exc}"
        cache[key] = result
        return result

    async def get_wallet_portfolio(address: str, chain: str = "ETH") -> str:
        """Get a wallet's full portfolio: native balance, transaction count, and top ERC-20 token holdings with symbols and amounts."""
        key = _cache_key("get_wallet_portfolio", {"address": address, "chain": chain})
        if key in cache:
            return cache[key]
        try:
            profile = await fetch_complete_wallet_profile(provider, address, chain)
            result = json.dumps(profile, default=str)
        except RateLimitError:
            return RATE_LIMIT_MSG
        except Exception as exc:
            return f"ERROR: could not fetch portfolio for {address} on {chain}: {exc}"
        cache[key] = result
        return result

    return [
        tool(get_wallet_info),
        tool(get_token_info),
        tool(trace_transaction),
        tool(get_wallet_portfolio),
    ]


def _wei_to_eth(hex_balance: str) -> str:
    try:
        wei = int(hex_balance, 16)
        return f"{wei / 10**18:.6f}"
    except (ValueError, TypeError):
        return "N/A"


def _format_trace(trace: dict[str, Any]) -> str:
    if not trace:
        return "no trace data available"
    from_addr = trace.get("from", "N/A")
    to_addr = trace.get("to", "N/A")
    value = _wei_to_eth(str(trace.get("value", "0x0")))
    return f"from={from_addr}, to={to_addr}, value={value} ETH, type={trace.get('type', 'CALL')}"
