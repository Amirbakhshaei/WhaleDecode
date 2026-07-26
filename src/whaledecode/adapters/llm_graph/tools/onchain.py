from langchain_core.tools import tool


@tool
async def get_wallet_info(address: str, chain: str = "ETH") -> str:
    """Get basic info about a wallet: balance, transaction count, and tags."""
    return f"Wallet {address} on {chain}: balance=0.0 ETH, tx_count=42, tags=['whale', 'defi']"


@tool
async def get_token_info(token_address: str, chain: str = "ETH") -> str:
    """Get token metadata: name, symbol, decimals, total supply."""
    return f"Token {token_address}: name=MockToken, symbol=MCK, decimals=18, total_supply=1_000_000"


@tool
async def trace_transaction(tx_hash: str, chain: str = "ETH") -> str:
    """Trace a transaction to see internal calls and value flow."""
    return f"Tx {tx_hash}: from=0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18, to=0x47ac0Fb4F2D84898e4D9E7b4DaB3C24507a6D503, value=10.0 ETH"


def create_onchain_tools() -> list:
    return [get_wallet_info, get_token_info, trace_transaction]
