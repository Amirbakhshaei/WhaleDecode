"""Tests for the deterministic low-RPM investigation graph."""
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from whaledecode.adapters.chain.providers.mock import MockChainProvider
from whaledecode.adapters.llm_graph.graphs.low_rpm_builder import build_low_rpm_graph
from whaledecode.adapters.llm_graph.tools.data_gatherer_tools import create_data_gatherer_tools


class _CountingLLM:
    """Fake chat model that records how many times it is invoked."""

    def __init__(self) -> None:
        self.invocations = 0

    async def ainvoke(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        self.invocations += 1
        return AIMessage(content=f"response_{self.invocations}")


def _http_client() -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if "dexscreener" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "pairs": [
                        {
                            "chainId": "ethereum",
                            "priceUsd": "1.23",
                            "liquidity": {"usd": 50000},
                            "volume": {"h24": 1000},
                            "pairAddress": "0xpair123",
                        }
                    ]
                },
            )
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _event() -> dict:
    return {
        "event_type": "LARGE_TRANSFER",
        "chain": "ETH",
        "tx_hash": "0x" + "a" * 64,
        "token_address": "0x" + "b" * 40,
    }


def _gatherer_tool_names() -> set[str]:
    return {t.name for t in create_data_gatherer_tools(MockChainProvider())}


def test_gatherer_equipped_only_with_defined_tools() -> None:
    assert _gatherer_tool_names() == {"etherscan_tool", "dexscreener_tool"}


@pytest.mark.asyncio
async def test_all_tools_are_langchain_tools() -> None:
    for t in create_data_gatherer_tools(MockChainProvider()):
        assert isinstance(t, BaseTool)


def test_low_rpm_graph_compiles() -> None:
    graph = build_low_rpm_graph(_CountingLLM(), http_client=_http_client())
    assert graph is not None
    nodes = {n for n in graph.get_graph().nodes if not n.startswith("__")}
    assert nodes == {"data_gatherer", "smc_analyst"}


@pytest.mark.asyncio
async def test_low_rpm_graph_full_run_is_deterministic_two_llm_calls() -> None:
    llm = _CountingLLM()
    graph = build_low_rpm_graph(llm, http_client=_http_client())

    result = await graph.ainvoke({"raw_event": _event()})

    assert llm.invocations == 2
    assert "response_1" in result["gathered_context"]
    assert result["final_thesis"] == "response_2"


@pytest.mark.asyncio
async def test_gatherer_populates_context_from_raw_event() -> None:
    llm = _CountingLLM()
    graph = build_low_rpm_graph(llm, http_client=_http_client())

    result = await graph.ainvoke({"raw_event": _event()})

    # etherscan tool output (trace of tx) must be present in gathered_context.
    assert "balance=" in result["gathered_context"]
    assert "Summary:" in result["gathered_context"]


@pytest.mark.asyncio
async def test_low_rpm_graph_compiles_with_async_postgres_saver() -> None:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    saver = AsyncPostgresSaver(conn=MagicMock())
    graph = build_low_rpm_graph(_CountingLLM(), checkpointer=saver, http_client=_http_client())
    assert graph is not None
