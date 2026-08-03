import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from whaledecode.evals.evaluators import heuristic_formatting_evaluator, make_smc_judge


class _Run:
    def __init__(self, summary: str) -> None:
        self.outputs = {"summary": summary}


class _Example:
    def __init__(self, event: dict, tool_outputs: dict) -> None:
        self.inputs = {"event": event, "tool_outputs": tool_outputs}
        self.outputs = {"reference_output": ""}


def _good_summary() -> str:
    return (
        "**MEV/Sandwich Attack**\n"
        "Smart money moved 500 ETH through a single contract.\n"
        "> **SMC Intelligence**\n"
        "> Directional significance: 0%.\n"
        "Tx: ||0xMEV1||\n"
        "From: ||0xmev_contract||"
    )


def test_heuristic_passes_well_formatted_output() -> None:
    result = heuristic_formatting_evaluator(_Run(_good_summary()), _Example({}, {}))
    assert result["score"] == 1.0


def test_heuristic_rejects_missing_spoiler_tags() -> None:
    output = _good_summary().replace("||0xMEV1||", "0xMEV1").replace("||0xmev_contract||", "0xmev_contract")
    result = heuristic_formatting_evaluator(_Run(output), _Example({}, {}))
    assert result["score"] < 1.0


def test_heuristic_rejects_raw_json_leak() -> None:
    output = _good_summary() + ' {"from": "0xmev_contract", "amount": 500}'
    result = heuristic_formatting_evaluator(_Run(output), _Example({}, {}))
    assert result["score"] < 1.0


@pytest.mark.asyncio
async def test_smc_judge_scores_one_on_consistent_output() -> None:
    llm = FakeMessagesListChatModel(responses=[AIMessage(content="1")])
    judge = make_smc_judge(llm)
    example = _Example({"chain": "ETH"}, {"trace_transaction": "500 ETH buy then sell"})
    result = await judge(_Run(_good_summary()), example)
    assert result["score"] == 1


@pytest.mark.asyncio
async def test_smc_judge_scores_zero_on_hallucination() -> None:
    llm = FakeMessagesListChatModel(responses=[AIMessage(content="0")])
    judge = make_smc_judge(llm)
    example = _Example({"chain": "ETH"}, {"trace_transaction": "no data"})
    result = await judge(_Run(_good_summary()), example)
    assert result["score"] == 0
