import pytest
from whaledecode.adapters.chain.providers.mock import MockChainProvider
from whaledecode.adapters.llm_graph.tools.onchain import create_onchain_tools
from whaledecode.adapters.llm_graph.tools.portfolio import fetch_complete_wallet_profile


class _SparseProvider(MockChainProvider):
    """Only the first known token has a balance: 1000 USDC (6 decimals)."""

    async def get_token_balances(self, chain, address, token_addresses):
        return {
            token.lower(): (10**6 * 1000 if i == 0 else 0)
            for i, token in enumerate(token_addresses)
        }

    async def get_token_metadata(self, chain, address):
        return {"name": "USD Coin", "symbol": "USDC", "decimals": 6}


@pytest.mark.asyncio
async def test_fetch_profile_includes_native_and_tx_count() -> None:
    profile = await fetch_complete_wallet_profile(MockChainProvider(), "0x1", "ETH")
    assert profile["chain"] == "ETH"
    assert profile["native_symbol"] == "ETH"
    assert isinstance(profile["native_balance"], float)
    assert isinstance(profile["tx_count"], int)
    assert profile["tokens"], "mock provider returns 1 token per known token"


@pytest.mark.asyncio
async def test_fetch_profile_resolves_symbols_and_amounts() -> None:
    profile = await fetch_complete_wallet_profile(_SparseProvider(), "0x1", "ARB")
    non_zero = [t for t in profile["tokens"] if t["amount"] > 0]
    assert len(non_zero) == 1
    assert non_zero[0]["symbol"] == "USDC"
    assert non_zero[0]["amount"] == 1000.0


@pytest.mark.asyncio
async def test_fetch_profile_skips_zero_tokens() -> None:
    profile = await fetch_complete_wallet_profile(_SparseProvider(), "0x1", "BASE")
    assert all(t["amount"] > 0 for t in profile["tokens"])


@pytest.mark.asyncio
async def test_wallet_portfolio_tool_returns_json() -> None:
    tools = {t.name: t for t in create_onchain_tools(MockChainProvider())}
    out = await tools["get_wallet_portfolio"].ainvoke({"address": "0x1", "chain": "ETH"})
    assert "native_balance" in out
    assert "tokens" in out
