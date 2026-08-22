import pytest
from whaledecode.adapters.chain.providers.http_rpc import RateLimitError
from whaledecode.adapters.chain.providers.mock import MockChainProvider
from whaledecode.adapters.llm_graph.tools.onchain import create_onchain_tools


class _FailingProvider(MockChainProvider):
    async def get_token_metadata(self, chain, address):
        raise RuntimeError("RPC unreachable")


class _RateLimitedProvider(MockChainProvider):
    async def get_balance(self, chain, address):
        raise RateLimitError("Rate limit reached on ETH for eth_getBalance")


class _CountingProvider(MockChainProvider):
    def __init__(self) -> None:
        self.token_calls = 0

    async def get_token_metadata(self, chain, address):
        self.token_calls += 1
        return {
            "name": f"Token-{address}",
            "symbol": "TKN",
            "decimals": 18,
        }


@pytest.mark.asyncio
async def test_token_info_uses_provider_data() -> None:
    tools = {t.name: t for t in create_onchain_tools(MockChainProvider())}
    out = await tools["get_token_info"].ainvoke({"token_address": "0x2"})
    assert "MockToken" in out
    assert "MCK" in out


@pytest.mark.asyncio
async def test_wallet_info_uses_provider_data() -> None:
    tools = {t.name: t for t in create_onchain_tools(MockChainProvider())}
    out = await tools["get_wallet_info"].ainvoke({"address": "0x1", "chain": "ETH"})
    assert "ERROR" not in out
    assert "balance=" in out


@pytest.mark.asyncio
async def test_token_info_cached_within_ttl() -> None:
    provider = _CountingProvider()
    tools = {t.name: t for t in create_onchain_tools(provider)}
    tool = tools["get_token_info"]

    first = await tool.ainvoke({"token_address": "0xcache"})
    second = await tool.ainvoke({"token_address": "0xcache"})

    assert first == second
    assert provider.token_calls == 1


@pytest.mark.asyncio
async def test_token_info_cache_key_includes_chain_and_address() -> None:
    provider = _CountingProvider()
    tools = {t.name: t for t in create_onchain_tools(provider)}
    tool = tools["get_token_info"]

    await tool.ainvoke({"token_address": "0xabc", "chain": "ETH"})
    await tool.ainvoke({"token_address": "0xdef", "chain": "ETH"})
    await tool.ainvoke({"token_address": "0xabc", "chain": "ARB"})

    assert provider.token_calls == 3


@pytest.mark.asyncio
async def test_trace_transaction_uses_provider_data() -> None:
    tools = {t.name: t for t in create_onchain_tools(MockChainProvider())}
    out = await tools["trace_transaction"].ainvoke({"tx_hash": "0xabc"})
    assert "from=" in out
    assert "value=" in out


@pytest.mark.asyncio
async def test_provider_error_returns_error_string_not_fabricated_data() -> None:
    tools = {t.name: t for t in create_onchain_tools(_FailingProvider())}
    out = await tools["get_token_info"].ainvoke({"token_address": "0x2"})
    assert "ERROR" in out
    assert "MockToken" not in out


@pytest.mark.asyncio
async def test_rate_limited_tool_returns_graceful_string() -> None:
    tools = {t.name: t for t in create_onchain_tools(_RateLimitedProvider())}
    out = await tools["get_wallet_info"].ainvoke({"address": "0x1", "chain": "ETH"})
    assert "Rate limit reached" in out
    assert "Proceed with existing context" in out
