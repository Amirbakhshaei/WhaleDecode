"""Deterministic low-RPM investigation graph.

A fixed DAG with static edges and exactly two LLM invocations per run:

    START -> data_gatherer -> smc_analyst -> END

- ``data_gatherer``: runs the two deterministic tools (etherscan + dexscreener)
  based on the raw_event, then ONE LLM call summarizes into ``gathered_context``.
- ``smc_analyst``: ONE LLM call, no tools, writes ``final_thesis`` markdown.

No conditional edges / tool-condition routing, so LLM call count is bounded by
construction — compliant with the shared 15 RPM budget.
"""
from __future__ import annotations

import httpx
from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from whaledecode.adapters.chain.providers.mock import MockChainProvider
from whaledecode.adapters.llm_graph.nodes.data_gatherer_node import create_data_gatherer_node
from whaledecode.adapters.llm_graph.nodes.smc_analyst_node import create_smc_analyst_node
from whaledecode.adapters.llm_graph.state.investigation_state import InvestigationState
from whaledecode.adapters.llm_graph.tools.data_gatherer_tools import create_data_gatherer_tools
from whaledecode.domain.ports.chain_provider import ChainProviderPort


def build_low_rpm_graph(
    llm: BaseChatModel,
    provider: ChainProviderPort | None = None,
    http_client: httpx.AsyncClient | None = None,
    checkpointer=None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
):
    workflow = StateGraph(InvestigationState)

    provider = provider or MockChainProvider()
    tools = create_data_gatherer_tools(provider, http_client=http_client)

    workflow.add_node(
        "data_gatherer",
        create_data_gatherer_node(llm, tools, session_factory=session_factory, http_client=http_client),
    )
    workflow.add_node("smc_analyst", create_smc_analyst_node(llm))

    workflow.add_edge(START, "data_gatherer")
    workflow.add_edge("data_gatherer", "smc_analyst")
    workflow.add_edge("smc_analyst", END)

    return workflow.compile(checkpointer=checkpointer)
