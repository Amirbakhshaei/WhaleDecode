import json

from whaledecode.adapters.llm_graph.utils import extract_clean_json


class TestExtractCleanJson:
    def test_plain_json_string(self):
        raw = '{"summary": "ok", "risk_score": 0.3}'
        assert extract_clean_json(raw) == {"summary": "ok", "risk_score": 0.3}

    def test_json_in_code_fence(self):
        raw = '```json\n{"summary": "ok", "risk_score": 0.8}\n```'
        result = extract_clean_json(raw)
        assert result["summary"] == "ok"
        assert result["risk_score"] == 0.8

    def test_json_in_plain_fence(self):
        raw = '```\n{"summary": "hello"}\n```'
        result = extract_clean_json(raw)
        assert result["summary"] == "hello"

    def test_gemini_content_blocks(self):
        blocks = [
            {"type": "text", "text": '{"summary": "block test", "risk_score": 0.6}'},
        ]
        result = extract_clean_json(blocks)
        assert result["summary"] == "block test"
        assert result["risk_score"] == 0.6

    def test_multiple_content_blocks_concatenated(self):
        blocks = [
            {"type": "text", "text": '{"summary": "part1'},
            {"type": "text", "text": '", "risk_score": 0.2}'},
        ]
        result = extract_clean_json(blocks)
        assert result["summary"] == "part1"
        assert result["risk_score"] == 0.2

    def test_list_of_strings(self):
        result = extract_clean_json(["not json at all"])
        assert result["summary"] == "not json at all"
        assert result["risk_score"] == 0.5

    def test_garbage_returns_fallback(self):
        result = extract_clean_json("not json at all")
        assert result["summary"] == "not json at all"
        assert result["risk_score"] == 0.5
        assert result["thesis"] == "Failed to parse structured output."

    def test_none_input(self):
        result = extract_clean_json(None)
        assert "summary" in result
        assert result["risk_score"] == 0.5

    def test_dict_input_passthrough(self):
        d = {"summary": "already dict", "risk_score": 0.9}
        result = extract_clean_json(d)
        assert result == d

    def test_json_with_surrounding_text(self):
        raw = 'Here is the analysis:\n{"summary": "whale move", "risk_score": 0.4}\nDone.'
        result = extract_clean_json(raw)
        # Should either parse or fallback
        assert "summary" in result

    def test_empty_list(self):
        result = extract_clean_json([])
        assert "summary" in result

    def test_evidence_preserved(self):
        raw = json.dumps({
            "summary": "ok",
            "risk_score": 0.5,
            "thesis": "test",
            "evidence": [{"fact": "moved 500M tokens", "source": "etherscan"}],
        })
        result = extract_clean_json(raw)
        assert len(result["evidence"]) == 1
        assert result["evidence"][0]["fact"] == "moved 500M tokens"
