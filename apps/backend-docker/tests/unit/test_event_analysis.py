from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from whaledecode.adapters.llm_graph.nodes.event_analysis import create_analysis_node
from whaledecode.domain.schemas.llm_outputs import EventAnalysisResult


class _RecordingModel:
    def __init__(self) -> None:
        self.calls: list[list] = []

    def with_structured_output(self, schema: Any, **kwargs: Any) -> "_RecordingModel":
        assert schema is EventAnalysisResult
        return self

    async def ainvoke(self, messages: list, **kwargs: Any) -> EventAnalysisResult:
        self.calls.append(messages)
        return EventAnalysisResult(
            entity_profile="Binance 16 -> Cold Storage (Institutional Accumulator)",
            context="Executed at 03:14 UTC, $15.2M magnitude.",
            impact="Removes ~3.8% of Binance liquid orderbook supply.",
        )


async def test_analyze_event_does_not_reinject_event_as_new_user_turn() -> None:
    model = _RecordingModel()
    node = create_analysis_node(model)

    state = {
        "event_data": {"event_type": "TRANSFER"},
        "messages": [
            HumanMessage(content='{"event_type": "TRANSFER"}'),
            AIMessage(
                content="",
                tool_calls=[{"name": "get_wallet_info", "args": {"address": "0x1"}, "id": "c1", "type": "tool_call"}],
            ),
            ToolMessage(content="balance=0.0", tool_call_id="c1"),
        ],
    }

    await node(state)

    assert len(model.calls) == 1
    sent = model.calls[0]
    roles = [type(m).__name__ for m in sent]
    assert roles == ["SystemMessage", "HumanMessage", "AIMessage", "ToolMessage"]


async def test_analyze_event_requires_opening_user_turn_from_state() -> None:
    model = _RecordingModel()
    node = create_analysis_node(model)

    await node(
        {
            "event_data": {"event_type": "TRANSFER"},
            "messages": [HumanMessage(content='{"event_type": "TRANSFER"}')],
        }
    )

    roles = [type(m).__name__ for m in model.calls[0]]
    assert roles == ["SystemMessage", "HumanMessage"]


async def test_analyze_event_injects_resolved_entity_labels_into_system_prompt() -> None:
    model = _RecordingModel()
    node = create_analysis_node(model)

    state = {
        "event_data": {
            "event_type": "TRANSFER",
            "from_entity": "Binance 16 (0xdfd5...abcd)",
            "to_entity": "Unlabeled EOA (0x91dd...beef)",
            "from_label": "Binance 16",
            "to_label": "Unlabeled EOA",
            "event_category": "CEX Outflow",
            "24h_vol_usd": "Unavailable",
        },
        "messages": [HumanMessage(content='{"event_type": "TRANSFER"}')],
    }

    await node(state)

    system = model.calls[0][0]
    assert "# EVENT ENTITIES" in system.content
    assert "from_entity: Binance 16 (0xdfd5...abcd)" in system.content
    assert "to_entity: Unlabeled EOA (0x91dd...beef)" in system.content
    assert "# MARKET CONTEXT" in system.content
    assert "from_label: Binance 16" in system.content
    assert "event_category: CEX Outflow" in system.content
    assert "24h_vol_usd: Unavailable" in system.content
    assert "ZERO RAW HEX ADDRESSES" in system.content


async def test_analyze_event_market_context_defaults_to_unavailable() -> None:
    model = _RecordingModel()
    node = create_analysis_node(model)

    await node(
        {
            "event_data": {"event_type": "TRANSFER"},
            "messages": [HumanMessage(content='{"event_type": "TRANSFER"}')],
        }
    )

    system = model.calls[0][0]
    assert "from_label: Unavailable" in system.content
    assert "24h_vol_usd: Unavailable" in system.content


async def test_analyze_event_omits_entity_block_when_labels_absent() -> None:
    model = _RecordingModel()
    node = create_analysis_node(model)

    await node(
        {
            "event_data": {"event_type": "TRANSFER"},
            "messages": [HumanMessage(content='{"event_type": "TRANSFER"}')],
        }
    )

    system = model.calls[0][0]
    assert "from_entity:" not in system.content
    assert "to_entity:" not in system.content
