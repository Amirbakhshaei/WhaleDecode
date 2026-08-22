"""generate_chat_report returns typed fields via with_structured_output."""
from typing import Any

from langchain_core.messages import AIMessage
from whaledecode.adapters.llm_graph.nodes.generate_chat_report import (
    create_chat_report_node,
)
from whaledecode.domain.schemas.llm_outputs import ChatReportResult


class _FakeStructured:
    def __init__(self, result: ChatReportResult) -> None:
        self._result = result

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ChatReportResult:
        return self._result


class _FakeModel:
    def with_structured_output(self, schema: Any, **kwargs: Any) -> _FakeStructured:
        assert schema is ChatReportResult
        return _FakeStructured(
            ChatReportResult(
                summary="Binance moved 2.1M USDC to a cold wallet.",
                risk_score=0.7,
                thesis="CEX outflow, accumulation signal.",
                evidence=[{"fact": "2.1M USDC", "source": "on-chain"}],
                tool_calls=[],
                disclaimer="Not financial advice.",
            )
        )


async def test_chat_report_returns_structured_fields() -> None:
    node = create_chat_report_node(_FakeModel())
    result = await node({"summary": "raw analysis text", "messages": []})

    assert isinstance(result["summary"], str) and result["summary"]
    assert result["risk_score"] == 0.7
    assert result["messages"] == [AIMessage(content="Binance moved 2.1M USDC to a cold wallet.")]
    assert result["evidence"] == [{"fact": "2.1M USDC", "source": "on-chain"}]
