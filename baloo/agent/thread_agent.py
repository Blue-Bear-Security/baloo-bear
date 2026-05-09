"""Thread conversation agent — classifies developer replies and generates responses."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from baloo.agent.config import get_agent_options
from baloo.agent.pi_runtime import PIAgentBase
from baloo.agent.thread_prompts import THREAD_AGENT_SYSTEM_PROMPT, build_thread_prompt
from baloo.config.settings import get_settings
from baloo.github.models import DiscussionComment

logger = logging.getLogger(__name__)

VALID_CLASSIFICATIONS = {
    "acknowledged",
    "disagreed_valid",
    "disagreed_invalid",
    "question",
    "unclear",
}


@dataclass
class ThreadAgentResult:
    """Result of a thread agent classification."""

    classification: str = "unclear"
    reply: str | None = None
    reasoning: str = ""
    feedback_signal: dict | None = None
    cost_usd: float = 0.0
    model: str = ""


class ThreadAgent:
    """Classify developer replies to Baloo findings and generate responses.

    Uses a cheap/fast model with no tools. Fail-safe: returns ``unclear``
    on any error so the thread is left open without a reply.
    """

    def __init__(self, model: str | None = None):
        settings = get_settings()
        self.model = model or settings.thread_agent_model

    async def classify(
        self,
        *,
        thread_comments: list[DiscussionComment],
        code_context: str,
        file_path: str,
        line_number: int,
    ) -> ThreadAgentResult:
        """Classify a developer's reply and generate a response.

        Args:
            thread_comments: Full thread history in chronological order.
            code_context: Current code around the finding location.
            file_path: Path to the file containing the finding.
            line_number: Line number of the finding.

        Returns:
            ThreadAgentResult with classification, optional reply, and optional feedback signal.
        """
        prompt = build_thread_prompt(
            thread_comments=thread_comments,
            code_context=code_context,
            file_path=file_path,
            line_number=line_number,
        )

        try:
            structured, metadata = await self._run_query(prompt)
        except Exception as exc:
            logger.warning("Thread agent failed: %s", exc)
            return ThreadAgentResult(classification="unclear")

        if not structured or not isinstance(structured, dict):
            logger.warning("Thread agent returned unparseable response")
            return ThreadAgentResult(classification="unclear")

        classification = structured.get("classification", "unclear")
        if classification not in VALID_CLASSIFICATIONS:
            classification = "unclear"

        reply = structured.get("reply")
        if reply and not isinstance(reply, str):
            reply = None

        feedback_signal = None
        if classification == "disagreed_valid":
            raw_signal = structured.get("feedback_signal")
            if isinstance(raw_signal, dict) and raw_signal.get("pattern"):
                feedback_signal = {
                    "pattern": raw_signal["pattern"],
                    "category": raw_signal.get("category", ""),
                    "file_glob": raw_signal.get("file_glob"),
                }

        return ThreadAgentResult(
            classification=classification,
            reply=reply,
            reasoning=structured.get("reasoning", ""),
            feedback_signal=feedback_signal,
            cost_usd=metadata.get("cost_usd", 0.0),
            model=metadata.get("model", self.model),
        )

    async def _run_query(self, prompt: str) -> tuple[dict | None, dict]:
        """Run the PI agent query. Separated for testability."""
        options = get_agent_options(
            model=self.model,
            thinking_level="off",
        )
        options.system_prompt = THREAD_AGENT_SYSTEM_PROMPT
        options.no_tools = True
        options.max_turns = 2

        agent = PIAgentBase(options)
        return await agent.run_query(prompt)
