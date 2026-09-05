from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from whaledecode.adapters.chain.providers.mock import MockChainProvider
from whaledecode.adapters.llm_graph.nodes.consolidated_report import create_consolidated_report_node
from whaledecode.adapters.llm_graph.nodes.event_analysis import create_analysis_node
from whaledecode.adapters.llm_graph.state.event_investigation import EventInvestigationState
from whaledecode.adapters.llm_graph.tools.data_gatherer_tools import create_data_gatherer_tools
from whaledecode.adapters.llm_graph.tools.onchain import create_onchain_tools
from whaledecode.adapters.pricing.oracle import PriceOracle
from whaledecode.domain.ports.chain_provider import ChainProviderPort

# Pre-LLM circuit breaker thresholds
MIN_CONVICTION_FOR_LLM = 75
MIN_VALUE_USD_FOR_LLM = 25_000.0


async def _circuit_breaker(state: EventInvestigationState, config: RunnableConfig) -> dict:
    """Pre-LLM circuit breaker: skip LLM if conviction < 75 or value_usd < $25k.

    Returns updated state with `skip_llm` flag set. Lower-tier events pass
    directly to DB without triggering LangGraph agents, saving 100% of LLM costs.
    """
    raw_event = state.get("raw_event") or {}
    value_usd = float(raw_event.get("value_usd", 0) or 0)

    # Get conviction score from event data or compute from context
    conviction_score = float(raw_event.get("conviction_score", 0) or 0)

    # Also check SMC analysis if available
    smc_analysis = state.get("smc_analysis")
    is_high_conviction_smc = False
    if smc_analysis and hasattr(smc_analysis, 'ote_confluence') and smc_analysis.ote_confluence:
        is_high_conviction_smc = True

    skip_llm = conviction_score < MIN_CONVICTION_FOR_LLM and value_usd < MIN_VALUE_USD_FOR_LLM and not is_high_conviction_smc

    return {"skip_llm": skip_llm, "conviction_score": conviction_score, "value_usd": value_usd}


async def _fetch_smc_analysis(state: EventInvestigationState, config: RunnableConfig) -> dict:
    """Fetch SMC market structure analysis from PriceOracle (DexScreener)."""
    raw_event = state.get("raw_event") or {}
    token_address = raw_event.get("address") or raw_event.get("contract_address") or ""
    chain = state.get("chain", "ethereum")

    if not token_address:
        return {"smc_analysis": None}

    try:
        oracle = PriceOracle()
        smc_result = await oracle.get_smc_analysis(token_address, chain)
        await oracle.aclose()
        return {"smc_analysis": smc_result}
    except Exception:
        return {"smc_analysis": None}


def _route_after_circuit_breaker(state: EventInvestigationState) -> str:
    """Route to LLM analysis or direct consolidation based on circuit breaker."""
    if state.get("skip_llm"):
        return "consolidate"
    return "fetch_smc"


def build_investigation_graph(llm: BaseChatModel, provider: ChainProviderPort | None = None):
    workflow = StateGraph(EventInvestigationState)

    provider = provider or MockChainProvider()
    tools = create_onchain_tools(provider) + create_data_gatherer_tools(provider)
    tool_node = ToolNode(tools)
    llm_with_tools = llm.bind_tools(tools)

    analyze_node = create_analysis_node(llm_with_tools)
    consolidate_node = create_consolidated_report_node(llm)

    workflow.add_node("circuit_breaker", _circuit_breaker)
    workflow.add_node("fetch_smc", _fetch_smc_analysis)
    workflow.add_node("analyze", analyze_node)
    workflow.add_node("execute_tools", tool_node)
    workflow.add_node("consolidate", consolidate_node)

    workflow.add_edge(START, "circuit_breaker")
    workflow.add_conditional_edges(
        "circuit_breaker",
        _route_after_circuit_breaker,
        {"fetch_smc": "fetch_smc", "consolidate": "consolidate"}
    )
    workflow.add_edge("fetch_smc", "analyze")
    workflow.add_conditional_edges("analyze", tools_condition, {"tools": "execute_tools", END: "consolidate"})
    workflow.add_edge("execute_tools", "analyze")
    workflow.add_edge("consolidate", END)

    return workflow.compile()
