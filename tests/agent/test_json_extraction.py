"""Tests for improved JSON extraction — specifically the reverse-scan strategy."""

from unittest.mock import patch

from baloo.agent.pi_runtime import _extract_json_from_text, _load_json_with_repair


class TestReverseScanExtraction:
    """Test JSON extraction when a long preamble precedes the JSON."""

    def test_long_preamble_then_json(self):
        """The exact failure pattern from production logs."""
        preamble = (
            "Based on my thorough analysis of the diff, I now have enough context "
            "to compile the review. Let me check one more specific pattern from the diff:\n\n"
            "The key things I need to verify from the diff code:\n\n"
            "1. In `openrouter/model.py`, `_build_prediction(self, severity, labels, "
            "confidence, reason)` - the `reason` parameter is accepted but the return "
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
            "Looking at the function:\n"
            '```python\ndef foo():\n    return {"key": "value"}\n```\n\n'
            "The issue is clear.\n\n"
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
        json_part = (
            '{"findings": [{"file": "a.py", "details": {"nested": {"deep": true}}}], "summary": {}}'
        )
        text = "Preamble with { braces }\n\n" + json_part
        result = _extract_json_from_text(text)
        assert result is not None
        assert result["findings"][0]["details"]["nested"]["deep"] is True

    def test_escaped_quotes_in_json_strings(self):
        """Reverse scan handles escaped quotes inside JSON string values."""
        json_part = (
            '{"findings": [{"file": "a.py", "body": "said \\"hello\\" world"}], "summary": {}}'
        )
        text = "Some preamble text\n\n" + json_part
        result = _extract_json_from_text(text)
        assert result is not None
        assert result["findings"][0]["body"] == 'said "hello" world'

    def test_escaped_backslash_before_quote(self):
        """Reverse scan distinguishes escaped backslash from escaped quote."""
        # String value ends with a literal backslash: "path\\"
        json_part = '{"findings": [], "summary": {"path": "C:\\\\"}}'
        text = "Preamble\n" + json_part
        result = _extract_json_from_text(text)
        assert result is not None
        assert result["summary"]["path"] == "C:\\"

    def test_repairs_unescaped_quotes_inside_string_values(self):
        """Production-shaped JSON with naked quotes inside a description still parses."""
        text = """{
  "findings": [
    {
      "file": "docs/human-in-the-loop.md",
      "line": 32,
      "severity": "CRITICAL",
      "category": "Security",
      "title": "Fail-open backend-error path documented without security warning",
      "description": "The timeout/failure table documents a convenience feature ("ensures a connectivity blip does not permanently stall the agent") rather than acknowledging the risk. This also conflicts with **"We prefer failing fast and loudly over silent fallbacks."**",
      "impact": "A backend outage can silently bypass the gate."
    }
  ],
  "summary": {
    "total_issues": 1,
    "critical": 1
  }
}"""
        result = _extract_json_from_text(text)
        assert result is not None
        assert result["findings"][0]["file"] == "docs/human-in-the-loop.md"
        assert (
            '("ensures a connectivity blip does not permanently stall the agent")'
            in result["findings"][0]["description"]
        )

    def test_repairs_literal_newlines_inside_string_values(self):
        """Literal newlines inside a string are escaped during repair."""
        text = """{
  "findings": [
    {
      "file": "a.py",
      "line": 1,
      "description": "First line
Second line"
    }
  ],
  "summary": {}
}"""
        result = _extract_json_from_text(text)
        assert result is not None
        assert result["findings"][0]["description"] == "First line\nSecond line"

    def test_repairs_inner_quote_followed_by_colon_inside_value_string(self):
        """A colon after an inner quote should not terminate a value string."""
        text = """{
  "findings": [
    {
      "description": "Use "key": value to configure",
      "impact": "High"
    }
  ],
  "summary": {}
}"""
        result = _extract_json_from_text(text)
        assert result is not None
        assert result["findings"][0]["description"] == 'Use "key": value to configure'
        assert result["findings"][0]["impact"] == "High"

    def test_logs_when_repair_attempt_still_fails(self):
        """A failed repair attempt should emit a diagnostic warning."""
        text = '{"description": "broken "term": still",, "impact": "High"}'
        with patch("baloo.agent.pi_runtime.logger.warning") as mock_warning:
            result = _load_json_with_repair(text)
        assert result is None
        mock_warning.assert_called_once()

    def test_handles_bare_keys_without_corrupting_quoted_values(self):
        """Bare keys should not cause the scanner to misidentify value strings as keys."""
        # This is invalid JSON ({key: "value"}) that we try to "not make worse"
        # during the string repair pass.
        text = '{key: "This is a "quoted" value", next: "ok"}'
        # _repair_json_string_literals should correctly see "This is a \"quoted\" value"
        # as a value string and terminate it at the last quote before the comma.
        from baloo.agent.pi_runtime import _repair_json_string_literals

        repaired = _repair_json_string_literals(text)
        # It should have escaped the inner quotes
        assert '\\"quoted\\"' in repaired
        # But it should NOT have escaped the closing quote of the value string
        assert 'value", next:' in repaired

    def test_no_json_at_all(self):
        """Still returns None when there's no JSON."""
        text = "This is just a text response with no JSON at all."
        result = _extract_json_from_text(text)
        assert result is None
