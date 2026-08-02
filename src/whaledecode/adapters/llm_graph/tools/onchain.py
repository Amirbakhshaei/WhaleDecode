from typing import Any

from langchain_core.tools import tool

from whaledecode.domain.ports.chain_provider import ChainProviderPort


def create_onchain_tools(provider: ChainProviderPort) -> list:
    # Bind the provider via closures so each graph gets its own tool instances.
    async def get_wallet_info(address: str, chain: str = "ETH") -> str:
        """Get basic info about a wallet: ETH balance and total transaction count."""
        try:
            balance = await provider.get_balance(chain, address)
            tx_count = await provider.get_transaction_count(chain, address)
            return f"Wallet {address} on {chain}: balance={_wei_to_eth(balance)} ETH, tx_count={tx_count}"
        except Exception as exc:
            return f"ERROR: could not fetch wallet info for {address} on {chain}: {exc}"

    async def get_token_info(token_address: str, chain: str = "ETH") -> str:
        """Get token metadata: name, symbol, decimals."""
        try:
            meta = await provider.get_token_metadata(chain, token_address)
            return (
                f"Token {token_address} on {chain}: name={meta.get('name')}, "
                f"symbol={meta.get('symbol')}, decimals={meta.get('decimals')}"
            )
        except Exception as exc:
            return f"ERROR: could not fetch token info for {token_address} on {chain}: {exc}"

    async def trace_transaction(tx_hash: str, chain: str = "ETH") -> str:
        """Trace a transaction to see internal calls and value flow."""
        try:
            trace = await provider.trace_call(chain, tx_hash)
            return f"Tx {tx_hash} on {chain}: {_format_trace(trace)}"
        except Exception as exc:
            return f"ERROR: could not trace {tx_hash} on {chain}: {exc}"

    return [
        tool(get_wallet_info),
        tool(get_token_info),
        tool(trace_transaction),
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
