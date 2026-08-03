from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from whaledecode.adapters.chain.providers.mock import MockChainProvider
from whaledecode.adapters.llm_graph.guardrails.safety import safety_guardrail
from whaledecode.adapters.llm_graph.nodes.chat_analysis import create_chat_analysis_node
from whaledecode.adapters.llm_graph.nodes.generate_chat_report import create_chat_report_node
from whaledecode.adapters.llm_graph.state.chat_investigation import ChatInvestigationState
from whaledecode.adapters.llm_graph.tools.onchain import create_onchain_tools
from whaledecode.domain.ports.chain_provider import ChainProviderPort


def build_chat_investigation_graph(
    llm: BaseChatModel,
    provider: ChainProviderPort | None = None,
    checkpointer=None,
):
    workflow = StateGraph(ChatInvestigationState)

    provider = provider or MockChainProvider()
    tools = create_onchain_tools(provider)
    tool_node = ToolNode(tools)
    llm_with_tools = llm.bind_tools(tools)

    analyze_node = create_chat_analysis_node(llm_with_tools)
    report_node = create_chat_report_node(llm)

    workflow.add_node("analyze", analyze_node)
    workflow.add_node("execute_tools", tool_node)
    workflow.add_node("report", report_node)
    workflow.add_node("guardrails", safety_guardrail)

    workflow.add_edge(START, "analyze")
    workflow.add_conditional_edges("analyze", tools_condition, {"tools": "execute_tools", END: "report"})
    workflow.add_edge("execute_tools", "analyze")
    workflow.add_edge("report", "guardrails")
    workflow.add_edge("guardrails", END)

    return workflow.compile(checkpointer=checkpointer)
