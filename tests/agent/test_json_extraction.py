"""Tests for improved JSON extraction — specifically the reverse-scan strategy."""

from baloo.agent.pi_runtime import _extract_json_from_text


class TestReverseScanExtraction:
    """Test JSON extraction when a long preamble precedes the JSON."""

    def test_long_preamble_then_json(self):
        """The exact failure pattern from production logs."""
        preamble = (
            "Based on my thorough analysis of the diff, I now have enough context "
            "to compile the review. Let me check one more specific pattern from the diff:\n\n"
            'The key things I need to verify from the diff code:\n\n'
            '1. In `openrouter/model.py`, `_build_prediction(self, severity, labels, '
            'confidence, reason)` - the `reason` parameter is accepted but the return '
            'dict {"result": result, "score": confidence, "model_version": config.OPENAI_MODEL} '
            "never includes it.\n\n"
            "2. Some other analysis text with braces { and } in it.\n\n"
        )
        json_part = '{"findings": [{"file": "a.py", "line": 10, "severity": "HIGH"}], "summary": {"total_issues": 1}}'
        text = preamble + json_part
        result = _extract_json_from_text(text)
        assert result is not None
        assert result["findings"][0]["file"] == "a.py"
        assert result["summary"]["total_issues"] == 1

    def test_preamble_with_code_blocks_and_braces(self):
        """Preamble containing code examples with braces."""
        preamble = (
            'Looking at the function:\n'
            '```python\ndef foo():\n    return {"key": "value"}\n```\n\n'
            'The issue is clear.\n\n'
        )
        json_part = '{"findings": [], "summary": {"total_issues": 0}}'
        text = preamble + json_part
        result = _extract_json_from_text(text)
        assert result is not None
        assert result["findings"] == []

    def test_preamble_with_inline_json_fragments(self):
        """Preamble containing JSON-like fragments that aren't the real output."""
        preamble = (
            'The return dict {"result": result, "score": confidence} never includes '
            'the reason field. Also {"key": broken is not valid JSON.\n\n'
        )
        json_part = '{"findings": [{"file": "b.py", "line": 5}], "summary": {}}'
        text = preamble + json_part
        result = _extract_json_from_text(text)
        assert result is not None
        assert result["findings"][0]["file"] == "b.py"

    def test_json_at_end_with_trailing_whitespace(self):
        """JSON at end with trailing newlines."""
        text = 'Some text\n\n{"findings": [], "summary": {}}\n\n'
        result = _extract_json_from_text(text)
        assert result is not None
        assert result["findings"] == []

    def test_plain_json_still_works(self):
        """Direct JSON parse strategy still takes priority."""
        text = '{"findings": [{"file": "c.py"}], "summary": {}}'
        result = _extract_json_from_text(text)
        assert result is not None
        assert result["findings"][0]["file"] == "c.py"

    def test_markdown_fence_still_works(self):
        """Markdown fence strategy still takes priority over reverse-scan."""
        text = 'Here is the result:\n```json\n{"findings": [], "summary": {}}\n```\nDone.'
        result = _extract_json_from_text(text)
        assert result is not None

    def test_deeply_nested_json_at_end(self):
        """Reverse scan handles nested braces correctly."""
        json_part = '{"findings": [{"file": "a.py", "details": {"nested": {"deep": true}}}], "summary": {}}'
        text = "Preamble with { braces }\n\n" + json_part
        result = _extract_json_from_text(text)
        assert result is not None
        assert result["findings"][0]["details"]["nested"]["deep"] is True

    def test_no_json_at_all(self):
        """Still returns None when there's no JSON."""
        text = "This is just a text response with no JSON at all."
        result = _extract_json_from_text(text)
        assert result is None
