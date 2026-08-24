"""Module 2: graph tracer — genesis-pick purity + BFS attribution with fakes."""
from whaledecode.services.graph_tracer import TraceResult, _pick_genesis_transfer

NOW = 1_000_000.0


def _transfer(frm, value, ts_s, tx="0xtx"):
    return {"from": frm, "to": "0xchild", "hash": tx, "value": str(value), "metadata": {"blockTimestamp": ts_s * 1000}}


def test_picks_largest_inbound_within_24h():
    transfers = [
        _transfer("0xsmall", 1, NOW - 100, "0xa"),
        _transfer("0xbig", 99, NOW - 50, "0xb"),
        _transfer("0xstale", 9999, NOW - 48 * 3600, "0xc"),  # outside window
        _transfer("", 500, NOW - 10, "0xd"),  # missing from
    ]
    genesis = _pick_genesis_transfer(transfers, NOW)
    assert genesis is not None
    assert genesis["from"] == "0xbig"


def test_no_recent_funding_returns_none():
    assert _pick_genesis_transfer([_transfer("0xold", 5, NOW - 72 * 3600)], NOW) is None


def test_trace_result_shape():
    empty = TraceResult("", "", 0, False, 0)
    assert empty.attributed_label == ""
