from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from whaledecode.adapters.llm_graph.utils import trim_history


def _pair(i: int) -> list:
    return [
        AIMessage(
            content="",
            tool_calls=[{"name": f"t{i}", "args": {"a": 1}, "id": f"c{i}", "type": "tool_call"}],
        ),
        ToolMessage(content="r" * 300, tool_call_id=f"c{i}"),
    ]


def test_empty_history_returns_empty() -> None:
    assert trim_history([]) == []


def test_trim_history_keeps_tail() -> None:
    messages = [SystemMessage(content="SYS")]
    for i in range(8):
        messages.extend(_pair(i))

    trimmed = trim_history(messages, max_tokens=120)

    assert len(trimmed) < len(messages)


def test_trim_history_never_splits_tool_pair() -> None:
    messages = [SystemMessage(content="SYS")]
    for i in range(8):
        messages.extend(_pair(i))

    trimmed = trim_history(messages, max_tokens=120)

    contents = [type(m).__name__ for m in trimmed]
    for j in range(0, len(contents), 2):
        assert contents[j] == "AIMessage"
        assert contents[j + 1] == "ToolMessage"


def test_trim_history_preserves_opening_user_turn() -> None:
    messages = [HumanMessage(content="Investigate this event")]
    for i in range(8):
        messages.extend(_pair(i))

    trimmed = trim_history(messages, max_tokens=80)

    assert isinstance(trimmed[0], HumanMessage)
    assert trimmed[0].content == "Investigate this event"
