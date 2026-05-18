"""Structured execution logger for review tasks."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from baloo.db.models import ReviewLog

logger = logging.getLogger(__name__)


class ReviewLogger:
    """Emits structured log events to the review_logs table.

    If review_id is None (database disabled), all methods are no-ops.
    Errors are swallowed to avoid crashing the review pipeline.
    """

    def __init__(
        self, review_id: int | None, session: Any = None, installation_id: str | None = None
    ):
        self._review_id = review_id
        self._session = session
        self._installation_id = installation_id

    @property
    def active(self) -> bool:
        return self._review_id is not None and self._session is not None

    async def _log(
        self,
        event_type: str,
        message: str,
        raw_text: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self.active:
            return
        try:
            row = ReviewLog(
                review_id=self._review_id,
                created_at=datetime.now(timezone.utc),
                event_type=event_type,
                message=message,
                raw_text=raw_text,
                metadata_json=json.dumps(metadata) if metadata else None,
                installation_id=self._installation_id,
            )
            self._session.add(row)
            await self._session.flush()
        except Exception as exc:
            logger.debug("ReviewLogger failed to write %s: %s", event_type, exc)

    async def agent_started(self, model: str, thinking_level: str) -> None:
        await self._log(
            "agent_started",
            f"Agent started with model {model}",
            metadata={"model": model, "thinking_level": thinking_level},
        )

    async def turn_completed(self, turn_number: int, tokens_in: int, tokens_out: int) -> None:
        await self._log(
            "turn_completed",
            f"Turn {turn_number} completed ({tokens_in} in / {tokens_out} out)",
            metadata={
                "turn_number": turn_number,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
            },
        )

    async def tool_use(self, tool_name: str, file_path: str | None = None) -> None:
        msg = f"Tool call: {tool_name}"
        if file_path:
            msg += f" ({file_path})"
        await self._log(
            "tool_use",
            msg,
            metadata={"tool_name": tool_name, "file_path": file_path},
        )

    async def json_parse_failed(self, raw_text: str, char_count: int) -> None:
        await self._log(
            "json_parse_failed",
            f"JSON extraction failed on {char_count} chars of assistant text",
            raw_text=raw_text,
            metadata={"char_count": char_count},
        )

    async def json_retry_started(self) -> None:
        await self._log("json_retry_started", "Spawning JSON retry subprocess")

    async def json_retry_failed(self, raw_text: str) -> None:
        await self._log(
            "json_retry_failed",
            "JSON retry also failed to produce valid JSON",
            raw_text=raw_text,
        )

    async def fallback_triggered(self, primary_model: str, fallback_model: str, error: str) -> None:
        await self._log(
            "fallback_triggered",
            f"Falling back from {primary_model} to {fallback_model}: {error[:200]}",
            metadata={
                "primary_model": primary_model,
                "fallback_model": fallback_model,
                "error": error[:500],
            },
        )

    async def agent_completed(
        self, tokens_in: int, tokens_out: int, cost: float, duration: float
    ) -> None:
        await self._log(
            "agent_completed",
            f"Agent completed ({tokens_in} in / {tokens_out} out, ${cost:.4f}, {duration:.1f}s)",
            metadata={
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost": cost,
                "duration": duration,
            },
        )

    async def agent_error(self, error_message: str, error_category: str = "") -> None:
        await self._log(
            "agent_error",
            f"Agent error: {error_message[:200]}",
            metadata={
                "error_message": error_message[:500],
                "error_category": error_category,
            },
        )
