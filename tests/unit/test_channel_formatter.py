from whaledecode.adapters.telegram.formatters.channel_formatter import (
    format_premium_event_post,
)

EVENT = {
    "chain": "ethereum",
    "tx_hash": "0x" + "ab" * 32,
    "raw_json": {
        "token": "PEPE",
        "amount": "500000000",
        "from": "0x" + "00" * 20,
        "to": "0x" + "ff" * 20,
        "value_usd": 4250.0,
    },
}


class TestFormatPremiumEventPost:
    def test_header_present(self):
        html = format_premium_event_post(EVENT, {"risk_score": 0.3})
        assert "WHALEDECODE" in html
        assert "PRO" in html

    def test_asset_line(self):
        html = format_premium_event_post(EVENT, {"risk_score": 0.3})
        assert "500,000,000" in html
        assert "PEPE" in html

    def test_network_line(self):
        html = format_premium_event_post(EVENT, {"risk_score": 0.3})
        assert "Ethereum" in html

    def test_value_line(self):
        html = format_premium_event_post(EVENT, {"risk_score": 0.3})
        assert "$4,250.00" in html

    def test_low_risk(self):
        html = format_premium_event_post(EVENT, {"risk_score": 0.2})
        assert "🟢" in html
        assert "LOW" in html
        assert "20%" in html

    def test_moderate_risk(self):
        html = format_premium_event_post(EVENT, {"risk_score": 0.55})
        assert "🟡" in html
        assert "MODERATE" in html
        assert "55%" in html

    def test_high_risk(self):
        html = format_premium_event_post(EVENT, {"risk_score": 0.85})
        assert "🔴" in html
        assert "HIGH" in html
        assert "85%" in html

    def test_summary_in_blockquote(self):
        html = format_premium_event_post(EVENT, {"summary": "Whale moved tokens"})
        assert "<blockquote>Whale moved tokens</blockquote>" in html

    def test_thesis_in_blockquote(self):
        html = format_premium_event_post(EVENT, {"thesis": "Bearish signal"})
        assert "<blockquote>Bearish signal</blockquote>" in html

    def test_evidence_rendered(self):
        analysis = {
            "risk_score": 0.3,
            "evidence": [
                {"fact": "Moved to CEX", "source": "etherscan"},
                {"fact": "Known mixer", "source": "arkham"},
            ],
        }
        html = format_premium_event_post(EVENT, analysis)
        assert "Moved to CEX" in html
        assert "Known mixer" in html
        assert "EVIDENCE" in html

    def test_no_evidence_section_when_empty(self):
        html = format_premium_event_post(EVENT, {"risk_score": 0.3, "evidence": []})
        assert "EVIDENCE" not in html

    def test_html_escaped(self):
        analysis = {"summary": "<script>alert(1)</script>", "risk_score": 0.3}
        html = format_premium_event_post(EVENT, analysis)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_explorer_link_contains_tx(self):
        html = format_premium_event_post(EVENT, {"risk_score": 0.3})
        tx = "0x" + "ab" * 32
        assert tx in html
        assert "etherscan.io/tx/" in html

    def test_code_tags_used(self):
        html = format_premium_event_post(EVENT, {"risk_score": 0.3})
        assert "<code>" in html

    def test_blockquote_tags_used(self):
        html = format_premium_event_post(EVENT, {"summary": "test"})
        assert "<blockquote>" in html

    def test_missing_raw_json_fallback(self):
        event_no_raw = {"chain": "bsc", "tx_hash": "0x" + "cc" * 32}
        html = format_premium_event_post(event_no_raw, {"risk_score": 0.1})
        assert "Bsc" in html
        assert "UNKNOWN" in html

    def test_zero_value(self):
        event_zero = {**EVENT, "raw_json": {**EVENT["raw_json"], "value_usd": 0}}
        html = format_premium_event_post(event_zero, {"risk_score": 0.1})
        assert "$0.00" in html
