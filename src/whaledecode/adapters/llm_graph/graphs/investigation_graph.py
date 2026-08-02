from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from whaledecode.adapters.llm_graph.formatting.briefing import format_briefing_node
from whaledecode.adapters.llm_graph.guardrails.safety import safety_guardrail
from whaledecode.adapters.llm_graph.nodes.event_analysis import create_analysis_node
from whaledecode.adapters.llm_graph.nodes.generate_report import create_report_node
from whaledecode.adapters.llm_graph.scoring.event_scorer import score_event_node
from whaledecode.adapters.llm_graph.state.event_investigation import EventInvestigationState
from whaledecode.adapters.llm_graph.tools.onchain import create_onchain_tools


def build_investigation_graph(llm: BaseChatModel):
    workflow = StateGraph(EventInvestigationState)

    tools = create_onchain_tools()
    tool_node = ToolNode(tools)
    llm_with_tools = llm.bind_tools(tools)

    analyze_node = create_analysis_node(llm_with_tools)
    report_node = create_report_node(llm)

    workflow.add_node("analyze", analyze_node)
    workflow.add_node("execute_tools", tool_node)
    workflow.add_node("report", report_node)
    workflow.add_node("score", score_event_node)
    workflow.add_node("guardrails", safety_guardrail)
    workflow.add_node("format", format_briefing_node)

    workflow.add_edge(START, "analyze")
    workflow.add_conditional_edges("analyze", tools_condition, {"tools": "execute_tools", END: "report"})
    workflow.add_edge("execute_tools", "analyze")
    workflow.add_edge("report", "score")
    workflow.add_edge("score", "guardrails")
    workflow.add_edge("guardrails", "format")
    workflow.add_edge("format", END)

    return workflow.compile()
