"""PI agent runtime — spawns pi in RPC mode as a subprocess.

This module replaces the previous claude-agent-sdk runtime with PI's
JSON-RPC subprocess protocol.  The agent is read-only: it can read files,
grep patterns, and list directories, but cannot execute commands, write
files, or modify anything.  All mutations (GitHub API calls, DB writes)
happen deterministically in the calling Python code.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from baloo.config.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class PIAgentOptions:
    """Configuration for a PI agent session."""

    model: str = "claude-sonnet-4-6"
    provider: str = "anthropic"
    system_prompt: str = ""
    thinking_level: str = "medium"
    max_turns: int = 20
    # Working directory for the agent (where it can read files)
    cwd: str | None = None


@dataclass
class PIRunResult:
    """Result of a PI agent run."""

    assistant_text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    num_turns: int = 0
    model: str = ""
    duration_seconds: float = 0.0
    is_error: bool = False
    error_message: str = ""


def _extract_json_from_text(text: str) -> dict | None:
    """
    Extract JSON object from assistant text.

    The agent is instructed to return JSON, but it may include markdown
    fences or surrounding text.  We try multiple strategies:
    1. Direct JSON parse
    2. Extract from ```json ... ``` fences
    3. Find the outermost { ... } block
    """
    stripped = text.strip()

    # Strategy 1: direct parse
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        pass

    # Strategy 2: extract from markdown fences
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", stripped, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            pass

    # Strategy 3: find outermost braces
    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        try:
            return json.loads(stripped[first_brace : last_brace + 1])
        except (json.JSONDecodeError, ValueError):
            pass

    return None


class PIAgentBase:
    """Base class for agents using PI's RPC subprocess protocol.

    Spawns ``pi --mode rpc --no-session`` and communicates via JSONL on
    stdin/stdout.  Only read-only tools are enabled.
    """

    def __init__(self, options: PIAgentOptions):
        self.options = options
        self.agent_name = self.__class__.__name__

    # -----------------------------------------------------------------
    # Low-level RPC helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _make_command(cmd_type: str, **kwargs: Any) -> str:
        """Build a JSON command line for the PI RPC protocol."""
        cmd: dict[str, Any] = {"type": cmd_type, "id": str(uuid.uuid4())}
        cmd.update(kwargs)
        return json.dumps(cmd) + "\n"

    @staticmethod
    async def _read_event(stdout: asyncio.StreamReader) -> dict | None:
        """Read one JSONL event from stdout, stripping \\r if present."""
        raw = await stdout.readline()
        if not raw:
            return None
        line = raw.decode("utf-8").rstrip("\r\n")
        if not line:
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            logger.debug("Ignoring non-JSON line from PI: %s", line[:200])
            return None

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    def _build_metadata(self, result: PIRunResult) -> Dict[str, Any]:
        """Build metadata dict from a PIRunResult."""
        return {
            "model": result.model or self.options.model,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "thinking_tokens": 0,
            "thinking_budget": None,
            "cost_usd": result.cost_usd,
            "num_turns": result.num_turns,
            "duration_seconds": result.duration_seconds,
        }

    # -----------------------------------------------------------------
    # Main query interface
    # -----------------------------------------------------------------

    async def run_query(self, query: str) -> Tuple[Any, Dict[str, Any]]:
        """Run a query through the PI agent and return structured output + metadata.

        Returns:
            Tuple of (parsed_json_output_or_None, metadata_dict)
        """
        settings = get_settings()
        start_time = time.time()
        result = PIRunResult()

        pi_binary = settings.pi_binary_path or "pi"
        cwd = self.options.cwd or None

        cmd = [
            pi_binary,
            "--mode", "rpc",
            "--no-session",
            "--provider", self.options.provider,
            "--model", f"{self.options.provider}/{self.options.model}",
            # Read-only tools only — no bash, no write, no edit
            "--tools", "read,grep,find,ls",
            # Inject system prompt
            "--system-prompt", self.options.system_prompt,
        ]

        logger.info(
            "%s: spawning PI process (model=%s, thinking=%s)",
            self.agent_name,
            self.options.model,
            self.options.thinking_level,
        )

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=10 * 1024 * 1024,  # 10 MB line buffer for large JSON-RPC responses
            cwd=cwd,
        )

        try:
            result = await self._drive_session(proc, query, start_time)
        except Exception as exc:
            logger.error("%s: PI session error: %s", self.agent_name, exc)
            result.is_error = True
            result.error_message = str(exc)
            # Re-raise so callers (e.g. fallback logic) can catch and retry
            elapsed = time.time() - start_time
            result.duration_seconds = elapsed
            metadata = self._build_metadata(result)
            err = RuntimeError(str(exc))
            err.metadata = metadata  # type: ignore[attr-defined]
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            raise err from exc
        finally:
            # Ensure process is cleaned up
            if proc.returncode is None:
                proc.kill()
                await proc.wait()

        elapsed = time.time() - start_time
        result.duration_seconds = elapsed
        metadata = self._build_metadata(result)

        if result.is_error:
            logger.warning(
                "%s failed: %s turns, tokens: %s in / %s out, cost: $%.4f, error: %s",
                self.agent_name,
                result.num_turns,
                result.input_tokens,
                result.output_tokens,
                result.cost_usd,
                result.error_message[:500],
            )
            if "prompt is too long" in result.error_message.lower():
                err = RuntimeError("Prompt is too long - PR diff exceeds context window")
                err.metadata = metadata  # type: ignore[attr-defined]
                raise err
        else:
            logger.info(
                "%s completed: %s turns, tokens: %s in / %s out, cost: $%.4f",
                self.agent_name,
                result.num_turns,
                result.input_tokens,
                result.output_tokens,
                result.cost_usd,
            )

        # Parse structured JSON from assistant text
        structured_output = _extract_json_from_text(result.assistant_text)

        if structured_output is None and result.assistant_text:
            logger.warning(
                "%s: could not parse JSON from assistant response (%d chars), "
                "requesting JSON retry",
                self.agent_name,
                len(result.assistant_text),
            )
            structured_output, retry_metadata = await self._retry_json(proc_cwd=cwd)
            if retry_metadata:
                # Accumulate retry costs into the main metadata
                metadata["input_tokens"] += retry_metadata.get("input_tokens", 0)
                metadata["output_tokens"] += retry_metadata.get("output_tokens", 0)
                metadata["cost_usd"] += retry_metadata.get("cost_usd", 0)
                metadata["num_turns"] += retry_metadata.get("num_turns", 0)
                metadata["json_retry"] = True

        return structured_output, metadata

    # -----------------------------------------------------------------
    # JSON retry
    # -----------------------------------------------------------------

    _JSON_RETRY_PROMPT = (
        "Your previous response could not be parsed as JSON. "
        "Please re-emit ONLY the JSON object matching the output schema "
        "from your analysis. No markdown fences, no explanation — just "
        "the raw JSON object with \"findings\" and \"summary\" keys."
    )

    async def _retry_json(
        self, *, proc_cwd: str | None
    ) -> Tuple[Any, Dict[str, Any] | None]:
        """Spawn a cheap follow-up session to ask the model to fix its JSON.

        Uses the same model but with thinking off and max 2 turns to keep
        cost minimal.  Returns (parsed_json_or_None, metadata_or_None).
        """
        settings = get_settings()
        pi_binary = settings.pi_binary_path or "pi"

        cmd = [
            pi_binary,
            "--mode", "rpc",
            "--no-session",
            "--provider", self.options.provider,
            "--model", f"{self.options.provider}/{self.options.model}",
            "--tools", "read,grep,find,ls",
            "--system-prompt", self.options.system_prompt,
        ]

        start = time.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=10 * 1024 * 1024,  # 10 MB line buffer for large JSON-RPC responses
                cwd=proc_cwd,
            )

            retry_opts = PIAgentOptions(
                model=self.options.model,
                provider=self.options.provider,
                system_prompt=self.options.system_prompt,
                thinking_level="off",
                max_turns=2,
            )
            # Temporarily swap options for the retry
            original_opts = self.options
            self.options = retry_opts
            try:
                result = await self._drive_session(
                    proc, self._JSON_RETRY_PROMPT, start
                )
            finally:
                self.options = original_opts
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()

            parsed = _extract_json_from_text(result.assistant_text)
            if parsed is not None:
                logger.info(
                    "%s: JSON retry succeeded (cost: $%.4f)",
                    self.agent_name,
                    result.cost_usd,
                )
            else:
                logger.warning("%s: JSON retry also failed to produce valid JSON", self.agent_name)

            return parsed, self._build_metadata(result)

        except Exception as exc:
            logger.warning("%s: JSON retry failed: %s", self.agent_name, exc)
            return None, None

    # -----------------------------------------------------------------
    # Session driver
    # -----------------------------------------------------------------

    async def _drive_session(
        self,
        proc: asyncio.subprocess.Process,
        query: str,
        start_time: float,
    ) -> PIRunResult:
        """Drive the RPC session: configure → prompt → collect events."""
        assert proc.stdin is not None
        assert proc.stdout is not None

        result = PIRunResult(model=self.options.model)

        async def send(cmd: str) -> None:
            proc.stdin.write(cmd.encode("utf-8"))  # type: ignore[union-attr]
            await proc.stdin.drain()  # type: ignore[union-attr]

        async def wait_response(expected_command: str) -> dict:
            """Read events until we get the response for the given command."""
            while True:
                event = await asyncio.wait_for(
                    self._read_event(proc.stdout),  # type: ignore[arg-type]
                    timeout=300,
                )
                if event is None:
                    raise RuntimeError("PI process closed stdout unexpectedly")
                if event.get("type") == "response" and event.get("command") == expected_command:
                    if not event.get("success"):
                        raise RuntimeError(
                            f"PI command '{expected_command}' failed: {event.get('error', 'unknown')}"
                        )
                    return event
                # Ignore other events while waiting for response

        # 1. Set thinking level
        await send(self._make_command("set_thinking_level", level=self.options.thinking_level))
        await wait_response("set_thinking_level")

        # 2. Send the prompt
        await send(self._make_command("prompt", message=query))
        await wait_response("prompt")

        # 3. Stream events until agent_end
        last_assistant_text = ""
        turn_count = 0

        while True:
            event = await asyncio.wait_for(
                self._read_event(proc.stdout),  # type: ignore[arg-type]
                timeout=600,  # 10 min max per review
            )
            if event is None:
                # Process closed
                break

            etype = event.get("type")

            if etype == "turn_end":
                turn_count += 1
                # Enforce max turns
                if turn_count >= self.options.max_turns:
                    logger.warning(
                        "%s: max turns (%d) reached, aborting",
                        self.agent_name,
                        self.options.max_turns,
                    )
                    await send(self._make_command("abort"))
                    # Don't wait for abort response, just collect agent_end
                    break

            elif etype == "message_end":
                msg = event.get("message", {})
                if msg.get("role") == "assistant":
                    # Extract text content
                    content = msg.get("content", [])
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif isinstance(block, str):
                            text_parts.append(block)
                    if text_parts:
                        last_assistant_text = "\n".join(text_parts)

                    # Accumulate usage
                    usage = msg.get("usage", {})
                    result.input_tokens += usage.get("input", 0)
                    result.output_tokens += usage.get("output", 0)
                    result.cache_read_tokens += usage.get("cacheRead", 0)
                    result.cache_write_tokens += usage.get("cacheWrite", 0)

                    cost = usage.get("cost", {})
                    if isinstance(cost, dict):
                        result.cost_usd += cost.get("total", 0) or 0

                    result.model = msg.get("model", result.model)

                    # Check for errors
                    stop_reason = msg.get("stopReason", "")
                    if stop_reason == "error":
                        result.is_error = True
                        result.error_message = "Agent returned error stop reason"

            elif etype == "tool_execution_start":
                tool = event.get("toolName", "?")
                logger.debug("%s: tool call → %s", self.agent_name, tool)

            elif etype == "agent_end":
                break

            elif etype == "message_update":
                # Streaming delta — we could log progress but we just collect at message_end
                pass

        result.assistant_text = last_assistant_text
        result.num_turns = turn_count

        return result
