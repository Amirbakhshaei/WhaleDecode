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
            briefing_markdown=(
                "⚡ **SUSPICIOUS_CONTRACT_CREATION** | `$50000`\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "🔹 **Network**: Ethereum\n"
                "🔹 **Amount**: `50000 USDC`\n\n"
                "**🔗 Execution Details**\n"
                "• **TX**: `0x9999da747864ed70dcb76e27a659ccfde383320c2738221b65b6f00845a90000`\n"
                "• **From**: `0x0000000000000000000000000000000000000000`\n"
                "• **To**: `0xffffffffffffffffffffffffffffffffffffffff`\n\n"
                "**🧠 Quantitative Assessment**\n"
                "Extreme holder concentration elevates rug-pull risk."
            ),
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
    assert "SUSPICIOUS_CONTRACT_CREATION" in result["summary"]
    assert "Execution Details" in result["summary"]
    assert "`0x9999da747864ed70dcb76e27a659ccfde383320c2738221b65b6f00845a90000`" in result["summary"]
    assert "HIGH RISK" in result["disclaimer"]
