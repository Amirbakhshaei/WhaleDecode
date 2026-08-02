import pytest
from whaledecode.adapters.chain.providers.mock import MockChainProvider
from whaledecode.adapters.llm_graph.tools.onchain import create_onchain_tools


class _FailingProvider(MockChainProvider):
    async def get_token_metadata(self, chain, address):
        raise RuntimeError("RPC unreachable")


@pytest.mark.asyncio
async def test_wallet_info_uses_provider_data() -> None:
    tools = {t.name: t for t in create_onchain_tools(MockChainProvider())}
    out = await tools["get_wallet_info"].ainvoke({"address": "0x1", "chain": "ETH"})
    assert "ERROR" not in out
    assert "balance=" in out


@pytest.mark.asyncio
async def test_token_info_uses_provider_data() -> None:
    tools = {t.name: t for t in create_onchain_tools(MockChainProvider())}
    out = await tools["get_token_info"].ainvoke({"token_address": "0x2"})
    assert "MockToken" in out
    assert "MCK" in out


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
