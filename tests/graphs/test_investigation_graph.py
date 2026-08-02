import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from whaledecode.adapters.llm_graph.graphs.investigation_graph import build_investigation_graph
from whaledecode.adapters.llm_graph.state.investigation_result import InvestigationResult


class _FakeStructuredOutput:
    def __init__(self, result: InvestigationResult) -> None:
        self._result = result

    async def ainvoke(self, *args: Any, **kwargs: Any) -> InvestigationResult:
        return self._result


class _FakeAnalysisModel:
    def __init__(self) -> None:
        self._structured = None

    def bind_tools(self, tools: list, **kwargs: Any) -> "_FakeAnalysisModel":
        return self

    def with_structured_output(self, schema: Any, **kwargs: Any) -> _FakeStructuredOutput:
        assert schema is InvestigationResult
        result = InvestigationResult(
            thesis="Rug-pull risk elevated",
            evidence=[{"fact": "Holder concentration is extreme", "source": "on-chain"}],
            risk_score=0.92,
            is_safe=False,
            briefing_markdown="**Investigation Report**\n\nExtreme holder concentration.",
            disclaimer="Not financial advice. HIGH RISK: significant uncertainty.",
        )
        self._structured = _FakeStructuredOutput(result)
        return self._structured

    async def ainvoke(self, *args: Any, **kwargs: Any) -> AIMessage:
        return AIMessage(content="Analysis complete")


def test_build_investigation_graph_compiles() -> None:
    graph = build_investigation_graph(_FakeAnalysisModel())
    assert graph is not None


@pytest.mark.asyncio
async def test_consolidated_graph_produces_full_result() -> None:
    graph = build_investigation_graph(_FakeAnalysisModel())
    event = {
        "event_type": "SUSPICIOUS_CONTRACT_CREATION",
        "chain": "ETH",
        "tx_hash": "0x9999da747864ed70dcb76e27a659ccfde383320c2738221b65b6f00845a90000",
        "notes": "Fetch on-chain holder distribution.",
    }
    result = await graph.ainvoke(
        {
            "event_data": event,
            "messages": [HumanMessage(content=json.dumps(event))],
        }
    )

    assert result["thesis"] == "Rug-pull risk elevated"
    assert result["evidence"] == [{"fact": "Holder concentration is extreme", "source": "on-chain"}]
    assert result["risk_score"] == 0.92
    assert result["is_safe"] is False
    assert "**Investigation Report**" in result["summary"]
    assert "HIGH RISK" in result["disclaimer"]
