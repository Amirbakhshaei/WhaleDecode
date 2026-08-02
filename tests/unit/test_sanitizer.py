from whaledecode.adapters.llm_graph.formatting.sanitizer import (
    KEYS_TO_IGNORE,
    sanitize_event_payload,
)


def test_ignores_rpc_protocol_noise_keys() -> None:
    raw = {
        "address": "0xabc",
        "topics": ["0x1", "0x2"],
        "data": "0xdef",
        "blockNumber": "0x10",
        "transactionIndex": "0x1",
        "logsBloom": "0x" + "00" * 256,
        "v": "0x1b",
        "r": "0x1",
        "s": "0x2",
    }
    compact = sanitize_event_payload(raw)
    assert "address" in compact
    assert "topics" in compact
    assert "blockNumber" not in compact
    assert "logsBloom" not in compact
    assert "v" not in compact
    assert "r" not in compact
    assert "s" not in compact
    assert "transactionIndex" not in compact


def test_truncates_long_lists_to_first_five() -> None:
    raw = {"topics": [f"0x{i}" for i in range(20)]}
    compact = sanitize_event_payload(raw)
    assert len(compact["topics"]) == 5


def test_keeps_short_lists_intact() -> None:
    raw = {"topics": ["0x1", "0x2"]}
    compact = sanitize_event_payload(raw)
    assert compact["topics"] == ["0x1", "0x2"]


def test_ignores_keys_are_a_set() -> None:
    assert isinstance(KEYS_TO_IGNORE, set)
    assert "blockHash" in KEYS_TO_IGNORE
