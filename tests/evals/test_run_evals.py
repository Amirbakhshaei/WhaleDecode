from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from whaledecode.adapters.chain.providers.mock import MockChainProvider
from whaledecode.adapters.llm_graph.state.investigation_result import InvestigationResult
from whaledecode.evals.run_evals import (
    ScriptedChainProvider,
    build_target,
    collect_failures,
    run_evals,
)


class _FakeStructuredOutput:
    async def ainvoke(self, *args: Any, **kwargs: Any) -> InvestigationResult:
        return InvestigationResult(
            thesis="MEV/Sandwich, 0% SMC significance",
            evidence=[{"fact": "500 ETH buy then sell", "source": "trace"}],
            risk_score=0.1,
            is_safe=True,
            briefing_markdown=(
                "**MEV/Sandwich Attack**\n"
                "0% SMC significance.\n"
                "Tx: ||0xMEV1||\n"
                "From: ||0xmev_contract||"
            ),
            disclaimer="Not financial advice.",
        )


class _FakeLLM:
    def bind_tools(self, tools: list, **kwargs: Any) -> "_FakeLLM":
        return self

    def with_structured_output(self, schema: Any, **kwargs: Any) -> _FakeStructuredOutput:
        return _FakeStructuredOutput()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> AIMessage:
        return AIMessage(content="Analysis complete")


@pytest.mark.asyncio
async def test_build_target_invokes_graph_and_returns_summary() -> None:
    target = build_target(_FakeLLM(), MockChainProvider())
    result = await target(
        {
            "event": {
                "chain": "ETH",
                "tx_hash": "0xMEV1",
                "block_number": 19500000,
                "event_type": "LARGE_TRANSFER",
            },
        }
    )
    assert "summary" in result
    assert "thesis" in result


@pytest.mark.asyncio
async def test_build_target_uses_scripted_provider_when_tool_outputs_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _fake_build(llm, provider):
        captured["provider"] = provider
        return _FakeGraph()

    monkeypatch.setattr("whaledecode.evals.run_evals.build_investigation_graph", _fake_build)
    target = build_target(_FakeLLM())
    await target(
        {
            "event": {"chain": "ETH", "tx_hash": "0xMEV1", "event_type": "LARGE_TRANSFER"},
            "tool_outputs": {"trace_call": {"from": "0xA", "to": "0xB", "value": "0x0", "type": "CALL"}},
        }
    )
    assert isinstance(captured["provider"], ScriptedChainProvider)


@pytest.mark.asyncio
async def test_scripted_provider_raises_on_error_timeout() -> None:
    provider = ScriptedChainProvider({"trace_call": "Error: Timeout"})
    with pytest.raises(TimeoutError):
        await provider.trace_call("ETH", "0xTIMEOUT1")


@pytest.mark.asyncio
async def test_scripted_provider_serves_case_data() -> None:
    provider = ScriptedChainProvider(
        {"trace_call": {"from": "0xA", "to": "0xB", "value": "0x0", "type": "CALL"}}
    )
    trace = await provider.trace_call("ETH", "0xWASH1")
    assert trace["from"] == "0xA"
    assert trace["to"] == "0xB"


class _FakeGraph:
    async def ainvoke(self, inputs: dict, config: dict | None = None) -> dict:
        return {
            "summary": "**MEV/Sandwich Attack**\n0% SMC significance.\nTx: ||0xMEV1||",
            "thesis": "MEV/Sandwich, 0% SMC significance",
            "risk_score": 0.1,
            "is_safe": True,
        }


@patch("whaledecode.evals.run_evals.evaluate")
def test_run_evals_applies_both_evaluators(mock_evaluate: MagicMock) -> None:
    client = MagicMock()
    llm = MagicMock()
    mock_evaluate.return_value.url = "https://smith.example/exp/1"
    mock_evaluate.return_value.__iter__.return_value = []

    run_evals(client=client, llm=llm)

    mock_evaluate.assert_called_once()
    _, kwargs = mock_evaluate.call_args
    assert kwargs["data"] == "WhaleDecode Golden Dataset"
    assert len(kwargs["evaluators"]) == 2


@patch("whaledecode.evals.run_evals.evaluate")
def test_run_evals_returns_experiment_url(mock_evaluate: MagicMock) -> None:
    client = MagicMock()
    llm = MagicMock()
    mock_evaluate.return_value.url = "https://smith.example/exp/42"
    mock_evaluate.return_value.__iter__.return_value = []

    url, failures = run_evals(client=client, llm=llm)

    assert url == "https://smith.example/exp/42"
    assert failures == []


def _row(eval_key: str, score: float) -> dict:
    return {
        "example": MagicMock(inputs={}, outputs={}),
        "run": MagicMock(error=None),
        "evaluation_results": {"results": [MagicMock(key=eval_key, score=score)]},
    }


def test_collect_failures_returns_empty_when_all_scores_full() -> None:
    rows = [_row("formatting", 1.0), _row("smc_soundness", 1.0)]
    assert collect_failures(rows) == []


def test_collect_failures_flags_below_threshold() -> None:
    rows = [_row("formatting", 1.0), _row("smc_soundness", 0.0)]
    failures = collect_failures(rows)
    assert len(failures) == 1
    assert failures[0]["key"] == "smc_soundness"
    assert failures[0]["score"] == 0.0
