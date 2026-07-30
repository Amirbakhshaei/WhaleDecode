from whaledecode.adapters.telegram.formatters.chat_formatter import format_investigation_result


class TestFormatInvestigationResult:
    def test_low_risk_score_shows_green(self):
        result = {"summary": "Test summary", "thesis": "Test thesis", "risk_score": 0.1}
        html = format_investigation_result(result)
        assert "🟢" in html
        assert "10%" in html

    def test_zero_risk_score_shows_green_not_hidden(self):
        result = {"summary": "Test summary", "thesis": "Test thesis", "risk_score": 0.0}
        html = format_investigation_result(result)
        assert "🟢" in html
        assert "0%" in html
        assert "Risk Score" in html

    def test_medium_risk_score_shows_yellow(self):
        result = {"summary": "Test summary", "thesis": "Test thesis", "risk_score": 0.5}
        html = format_investigation_result(result)
        assert "🟡" in html
        assert "50%" in html

    def test_high_risk_score_shows_red(self):
        result = {"summary": "Test summary", "thesis": "Test thesis", "risk_score": 0.9}
        html = format_investigation_result(result)
        assert "🔴" in html
        assert "90%" in html

    def test_boundary_low_to_medium(self):
        result = {"summary": "s", "thesis": "t", "risk_score": 0.3}
        html = format_investigation_result(result)
        assert "🟡" in html

    def test_boundary_medium_to_high(self):
        result = {"summary": "s", "thesis": "t", "risk_score": 0.71}
        html = format_investigation_result(result)
        assert "🔴" in html

    def test_07_is_yellow_not_red(self):
        result = {"summary": "s", "thesis": "t", "risk_score": 0.7}
        html = format_investigation_result(result)
        assert "🟡" in html

    def test_includes_summary(self):
        result = {"summary": "Whale moved 500 ETH", "thesis": "Bearish", "risk_score": 0.2}
        html = format_investigation_result(result)
        assert "Whale moved 500 ETH" in html
        assert "Summary" in html

    def test_includes_thesis(self):
        result = {"summary": "s", "thesis": "Smart money exiting", "risk_score": 0.2}
        html = format_investigation_result(result)
        assert "Smart money exiting" in html
        assert "Thesis" in html

    def test_missing_risk_score_defaults_to_zero(self):
        result = {"summary": "s", "thesis": "t"}
        html = format_investigation_result(result)
        assert "🟢" in html
        assert "0%" in html

    def test_html_escaped(self):
        result = {"summary": "<script>alert(1)</script>", "thesis": "t", "risk_score": 0.1}
        html = format_investigation_result(result)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_no_raw_json(self):
        result = {"summary": "s", "thesis": "t", "risk_score": 0.5, "evidence": [{"fact": "x"}]}
        html = format_investigation_result(result)
        assert "{" not in html or "Evidence" in html
