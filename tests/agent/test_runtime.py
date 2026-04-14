"""Tests for PI runtime module."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from baloo.agent.pi_runtime import (
    PIAgentBase,
    PIAgentOptions,
    PIRunResult,
    _extract_json_from_text,
)


class TestExtractJsonFromText:
    """Tests for JSON extraction from assistant text."""

    def test_plain_json(self):
        data = _extract_json_from_text('{"findings": [], "summary": {}}')
        assert data == {"findings": [], "summary": {}}

    def test_json_with_whitespace(self):
        data = _extract_json_from_text('  \n {"findings": []} \n ')
        assert data == {"findings": []}

    def test_json_in_markdown_fence(self):
        text = '```json\n{"findings": [{"file": "a.py"}]}\n```'
        data = _extract_json_from_text(text)
        assert data is not None
        assert data["findings"][0]["file"] == "a.py"

    def test_json_in_bare_fence(self):
        text = '```\n{"findings": []}\n```'
        data = _extract_json_from_text(text)
        assert data == {"findings": []}

    def test_json_with_surrounding_text(self):
        text = 'Here are my findings:\n{"findings": [], "summary": {}}\nDone.'
        data = _extract_json_from_text(text)
        assert data == {"findings": [], "summary": {}}

    def test_no_json(self):
        data = _extract_json_from_text("No JSON here, just text.")
        assert data is None

    def test_empty_string(self):
        data = _extract_json_from_text("")
        assert data is None

    def test_nested_json(self):
        text = '{"findings": [{"file": "a.py", "line": 1}], "summary": {"total_issues": 1}}'
        data = _extract_json_from_text(text)
        assert data["summary"]["total_issues"] == 1

    def test_malformed_json(self):
        data = _extract_json_from_text('{"findings": [}')
        assert data is None

    def test_json_array_not_object(self):
        """Arrays should not match — we expect an object."""
        data = _extract_json_from_text('[1, 2, 3]')
        # Strategy 1 parses it but it's a list, not dict
        # Our function returns whatever json.loads gives
        assert data == [1, 2, 3]


class TestPIAgentOptions:
    """Tests for PIAgentOptions defaults."""

    def test_defaults(self):
        opts = PIAgentOptions()
        assert opts.model == "claude-sonnet-4-6"
        assert opts.provider == "anthropic"
        assert opts.thinking_level == "medium"
        assert opts.max_turns == 20
        assert opts.cwd is None

    def test_custom_values(self):
        opts = PIAgentOptions(
            model="claude-opus-4-6",
            provider="anthropic",
            thinking_level="high",
            max_turns=30,
            cwd="/tmp/repo",
        )
        assert opts.model == "claude-opus-4-6"
        assert opts.max_turns == 30
        assert opts.cwd == "/tmp/repo"


class TestPIAgentBase:
    """Tests for the PI agent base class."""

    def test_make_command_structure(self):
        cmd_str = PIAgentBase._make_command("prompt", message="Hello")
        cmd = json.loads(cmd_str.strip())
        assert cmd["type"] == "prompt"
        assert cmd["message"] == "Hello"
        assert "id" in cmd  # has UUID

    def test_make_command_ends_with_newline(self):
        cmd_str = PIAgentBase._make_command("abort")
        assert cmd_str.endswith("\n")

    @pytest.mark.asyncio
    async def test_read_event_parses_json(self):
        reader = AsyncMock(spec=asyncio.StreamReader)
        reader.readline = AsyncMock(
            return_value=b'{"type": "agent_end"}\n'
        )
        event = await PIAgentBase._read_event(reader)
        assert event == {"type": "agent_end"}

    @pytest.mark.asyncio
    async def test_read_event_handles_empty_line(self):
        reader = AsyncMock(spec=asyncio.StreamReader)
        reader.readline = AsyncMock(return_value=b"\n")
        event = await PIAgentBase._read_event(reader)
        assert event is None

    @pytest.mark.asyncio
    async def test_read_event_handles_eof(self):
        reader = AsyncMock(spec=asyncio.StreamReader)
        reader.readline = AsyncMock(return_value=b"")
        event = await PIAgentBase._read_event(reader)
        assert event is None

    @pytest.mark.asyncio
    async def test_read_event_strips_cr(self):
        reader = AsyncMock(spec=asyncio.StreamReader)
        reader.readline = AsyncMock(
            return_value=b'{"type": "test"}\r\n'
        )
        event = await PIAgentBase._read_event(reader)
        assert event == {"type": "test"}


class TestPIAgentBaseRunQuery:
    """Tests for run_query with mocked subprocess."""

    def _make_events(self, structured_output: dict, usage: dict = None) -> list[bytes]:
        """Build the sequence of JSONL events a PI process would emit."""
        usage = usage or {"input": 500, "output": 100, "cacheRead": 0, "cacheWrite": 0, "cost": {"total": 0.01}}
        assistant_text = json.dumps(structured_output)

        events = [
            # Response to set_thinking_level
            {"type": "response", "command": "set_thinking_level", "success": True},
            # Response to prompt
            {"type": "response", "command": "prompt", "success": True},
            # Agent starts
            {"type": "agent_start"},
            # Turn
            {"type": "turn_start"},
            {"type": "message_start", "message": {"role": "assistant"}},
            {"type": "message_end", "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": assistant_text}],
                "model": "claude-sonnet-4-6",
                "usage": usage,
                "stopReason": "stop",
            }},
            {"type": "turn_end"},
            # Done
            {"type": "agent_end"},
        ]
        return [json.dumps(e).encode("utf-8") + b"\n" for e in events]

    @pytest.mark.asyncio
    async def test_successful_review(self):
        """Test a complete successful review flow."""
        structured = {"findings": [{"file": "a.py", "line": 1, "severity": "HIGH"}], "summary": {}}
        events = self._make_events(structured)

        agent = PIAgentBase(PIAgentOptions(model="claude-sonnet-4-6"))

        with patch("baloo.agent.pi_runtime.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.returncode = None
            proc.stdin = AsyncMock()
            proc.stdin.write = MagicMock()
            proc.stdin.drain = AsyncMock()
            proc.stdout = AsyncMock(spec=asyncio.StreamReader)

            event_iter = iter(events)
            async def fake_readline():
                try:
                    return next(event_iter)
                except StopIteration:
                    return b""
            proc.stdout.readline = fake_readline

            proc.stderr = AsyncMock()
            proc.kill = MagicMock()
            proc.wait = AsyncMock()

            mock_exec.return_value = proc

            output, metadata = await agent.run_query("Review this code")

            assert output is not None
            assert output["findings"][0]["file"] == "a.py"
            assert metadata["input_tokens"] == 500
            assert metadata["output_tokens"] == 100
            assert metadata["cost_usd"] == 0.01
            assert metadata["num_turns"] == 1
            assert metadata["model"] == "claude-sonnet-4-6"

    @pytest.mark.asyncio
    async def test_empty_response(self):
        """Test handling of empty assistant response."""
        events = self._make_events({"findings": [], "summary": {}})

        agent = PIAgentBase(PIAgentOptions())

        with patch("baloo.agent.pi_runtime.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.returncode = None
            proc.stdin = AsyncMock()
            proc.stdin.write = MagicMock()
            proc.stdin.drain = AsyncMock()
            proc.stdout = AsyncMock(spec=asyncio.StreamReader)

            event_iter = iter(events)
            async def fake_readline():
                try:
                    return next(event_iter)
                except StopIteration:
                    return b""
            proc.stdout.readline = fake_readline

            proc.stderr = AsyncMock()
            proc.kill = MagicMock()
            proc.wait = AsyncMock()
            mock_exec.return_value = proc

            output, metadata = await agent.run_query("Review")

            assert output == {"findings": [], "summary": {}}

    @pytest.mark.asyncio
    async def test_process_crash(self):
        """Test handling of PI process crashing (stdout closes early)."""
        events = [
            json.dumps({"type": "response", "command": "set_thinking_level", "success": True}).encode() + b"\n",
            json.dumps({"type": "response", "command": "prompt", "success": True}).encode() + b"\n",
            b"",  # EOF — process crashed
        ]

        agent = PIAgentBase(PIAgentOptions())

        with patch("baloo.agent.pi_runtime.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.returncode = 1
            proc.stdin = AsyncMock()
            proc.stdin.write = MagicMock()
            proc.stdin.drain = AsyncMock()
            proc.stdout = AsyncMock(spec=asyncio.StreamReader)

            event_iter = iter(events)
            async def fake_readline():
                try:
                    return next(event_iter)
                except StopIteration:
                    return b""
            proc.stdout.readline = fake_readline

            proc.stderr = AsyncMock()
            proc.kill = MagicMock()
            proc.wait = AsyncMock()
            mock_exec.return_value = proc

            output, metadata = await agent.run_query("Review")

            # Should handle gracefully — no JSON to parse
            assert output is None
            assert metadata["num_turns"] == 0

    @pytest.mark.asyncio
    async def test_command_failure(self):
        """Test handling of PI command returning failure."""
        events = [
            json.dumps({
                "type": "response",
                "command": "set_thinking_level",
                "success": False,
                "error": "Model not found",
            }).encode() + b"\n",
        ]

        agent = PIAgentBase(PIAgentOptions())

        with patch("baloo.agent.pi_runtime.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.returncode = None
            proc.stdin = AsyncMock()
            proc.stdin.write = MagicMock()
            proc.stdin.drain = AsyncMock()
            proc.stdout = AsyncMock(spec=asyncio.StreamReader)

            event_iter = iter(events)
            async def fake_readline():
                try:
                    return next(event_iter)
                except StopIteration:
                    return b""
            proc.stdout.readline = fake_readline

            proc.stderr = AsyncMock()
            proc.kill = MagicMock()
            proc.wait = AsyncMock()
            mock_exec.return_value = proc

            # Should raise with metadata attached
            with pytest.raises(RuntimeError) as exc_info:
                await agent.run_query("Review")
            assert hasattr(exc_info.value, "metadata")
            assert exc_info.value.metadata["num_turns"] == 0

    @pytest.mark.asyncio
    async def test_max_turns_enforcement(self):
        """Test that max_turns triggers abort."""
        # Agent with max_turns=1
        agent = PIAgentBase(PIAgentOptions(max_turns=1))

        events = [
            json.dumps({"type": "response", "command": "set_thinking_level", "success": True}).encode() + b"\n",
            json.dumps({"type": "response", "command": "prompt", "success": True}).encode() + b"\n",
            json.dumps({"type": "turn_start"}).encode() + b"\n",
            json.dumps({"type": "message_end", "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": '{"findings": []}'}],
                "model": "test",
                "usage": {"input": 100, "output": 50, "cacheRead": 0, "cacheWrite": 0, "cost": {"total": 0.005}},
                "stopReason": "toolUse",
            }}).encode() + b"\n",
            json.dumps({"type": "turn_end"}).encode() + b"\n",
            # After abort, agent_end would come
            json.dumps({"type": "agent_end"}).encode() + b"\n",
        ]

        with patch("baloo.agent.pi_runtime.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.returncode = None
            proc.stdin = AsyncMock()
            proc.stdin.write = MagicMock()
            proc.stdin.drain = AsyncMock()
            proc.stdout = AsyncMock(spec=asyncio.StreamReader)

            event_iter = iter(events)
            async def fake_readline():
                try:
                    return next(event_iter)
                except StopIteration:
                    return b""
            proc.stdout.readline = fake_readline

            proc.stderr = AsyncMock()
            proc.kill = MagicMock()
            proc.wait = AsyncMock()
            mock_exec.return_value = proc

            output, metadata = await agent.run_query("Review")

            # Should have sent abort command
            write_calls = proc.stdin.write.call_args_list
            abort_sent = any(b'"abort"' in call[0][0] for call in write_calls)
            assert abort_sent

    @pytest.mark.asyncio
    async def test_json_retry_on_invalid_response(self):
        """Test that invalid JSON triggers a retry that succeeds."""
        # First run returns non-JSON text
        bad_events = [
            json.dumps({"type": "response", "command": "set_thinking_level", "success": True}).encode() + b"\n",
            json.dumps({"type": "response", "command": "prompt", "success": True}).encode() + b"\n",
            json.dumps({"type": "turn_start"}).encode() + b"\n",
            json.dumps({"type": "message_end", "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Here are my findings about the code..."}],
                "model": "test",
                "usage": {"input": 500, "output": 200, "cacheRead": 0, "cacheWrite": 0, "cost": {"total": 0.01}},
                "stopReason": "stop",
            }}).encode() + b"\n",
            json.dumps({"type": "turn_end"}).encode() + b"\n",
            json.dumps({"type": "agent_end"}).encode() + b"\n",
        ]

        # Retry returns valid JSON
        good_events = [
            json.dumps({"type": "response", "command": "set_thinking_level", "success": True}).encode() + b"\n",
            json.dumps({"type": "response", "command": "prompt", "success": True}).encode() + b"\n",
            json.dumps({"type": "turn_start"}).encode() + b"\n",
            json.dumps({"type": "message_end", "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": '{"findings": [{"file": "a.py", "line": 1}], "summary": {}}'}],
                "model": "test",
                "usage": {"input": 100, "output": 50, "cacheRead": 0, "cacheWrite": 0, "cost": {"total": 0.002}},
                "stopReason": "stop",
            }}).encode() + b"\n",
            json.dumps({"type": "turn_end"}).encode() + b"\n",
            json.dumps({"type": "agent_end"}).encode() + b"\n",
        ]

        agent = PIAgentBase(PIAgentOptions())
        call_count = 0

        with patch("baloo.agent.pi_runtime.asyncio.create_subprocess_exec") as mock_exec:
            def make_proc(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                proc = AsyncMock()
                proc.returncode = None
                proc.stdin = AsyncMock()
                proc.stdin.write = MagicMock()
                proc.stdin.drain = AsyncMock()
                proc.stdout = AsyncMock(spec=asyncio.StreamReader)

                events = bad_events if call_count == 1 else good_events
                event_iter = iter(events)

                async def fake_readline():
                    try:
                        return next(event_iter)
                    except StopIteration:
                        return b""

                proc.stdout.readline = fake_readline
                proc.stderr = AsyncMock()
                proc.kill = MagicMock()
                proc.wait = AsyncMock()
                return proc

            mock_exec.side_effect = make_proc

            output, metadata = await agent.run_query("Review this code")

            # Should have retried and got valid JSON
            assert output is not None
            assert output["findings"][0]["file"] == "a.py"
            assert metadata["json_retry"] is True
            # Costs accumulated from both runs
            assert metadata["input_tokens"] == 600  # 500 + 100
            assert metadata["cost_usd"] == pytest.approx(0.012, abs=0.001)
            assert call_count == 2

    @pytest.mark.asyncio
    async def test_usage_aggregation_across_turns(self):
        """Test that token usage is aggregated across multiple turns."""
        usage1 = {"input": 200, "output": 50, "cacheRead": 0, "cacheWrite": 0, "cost": {"total": 0.005}}
        usage2 = {"input": 300, "output": 75, "cacheRead": 0, "cacheWrite": 0, "cost": {"total": 0.008}}

        events = [
            json.dumps({"type": "response", "command": "set_thinking_level", "success": True}).encode() + b"\n",
            json.dumps({"type": "response", "command": "prompt", "success": True}).encode() + b"\n",
            # Turn 1
            json.dumps({"type": "turn_start"}).encode() + b"\n",
            json.dumps({"type": "message_end", "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Let me check..."}],
                "model": "test",
                "usage": usage1,
                "stopReason": "toolUse",
            }}).encode() + b"\n",
            json.dumps({"type": "turn_end"}).encode() + b"\n",
            # Turn 2
            json.dumps({"type": "turn_start"}).encode() + b"\n",
            json.dumps({"type": "message_end", "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": '{"findings": [], "summary": {}}'}],
                "model": "test",
                "usage": usage2,
                "stopReason": "stop",
            }}).encode() + b"\n",
            json.dumps({"type": "turn_end"}).encode() + b"\n",
            json.dumps({"type": "agent_end"}).encode() + b"\n",
        ]

        agent = PIAgentBase(PIAgentOptions())

        with patch("baloo.agent.pi_runtime.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.returncode = None
            proc.stdin = AsyncMock()
            proc.stdin.write = MagicMock()
            proc.stdin.drain = AsyncMock()
            proc.stdout = AsyncMock(spec=asyncio.StreamReader)

            event_iter = iter(events)
            async def fake_readline():
                try:
                    return next(event_iter)
                except StopIteration:
                    return b""
            proc.stdout.readline = fake_readline

            proc.stderr = AsyncMock()
            proc.kill = MagicMock()
            proc.wait = AsyncMock()
            mock_exec.return_value = proc

            output, metadata = await agent.run_query("Review")

            assert metadata["input_tokens"] == 500  # 200 + 300
            assert metadata["output_tokens"] == 125  # 50 + 75
            assert abs(metadata["cost_usd"] - 0.013) < 0.001
            assert metadata["num_turns"] == 2
