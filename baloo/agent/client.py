"""PI-based agent client for code review."""

import logging
from typing import Any

from baloo.agent.config import get_agent_options
from baloo.agent.pi_runtime import PIAgentBase
from baloo.agent.prompts import (
    build_pr_review_prompt,
)
from baloo.agent.schemas import findings_to_comments
from baloo.github.models import PRContext, ReviewResult
from baloo.processor.decision_engine import DecisionEngine
from baloo.processor.formatter import CommentFormatter

logger = logging.getLogger(__name__)


class BalooAgent(PIAgentBase):
    """Code review agent powered by PI."""

    def __init__(self, model_override: str = None):
        """Initialize agent with options."""
        options = get_agent_options(model_override)
        super().__init__(options)
        logger.info(f"Initialized BalooAgent with {self.options.model}")

    async def review_pr(self, pr_context: PRContext, model_override: str = None) -> ReviewResult:
        """
        Perform a full code review for a pull request.

        Args:
            pr_context: Context about the PR including diff and metadata
            model_override: Optional model to use for this review

        Returns:
            ReviewResult containing summary, comments, and decision
        """
        if model_override:
            self.options = get_agent_options(model_override)

        logger.info(
            f"Starting review for {pr_context.repo_full_name}#{pr_context.pr_number} using {self.options.model}"
        )

        try:
            # Build review prompt
            review_query = build_pr_review_prompt(pr_context)

            # Create execution logger if database is enabled
            review_logger = None
            logger_session = None
            review_id = getattr(pr_context, '_review_id', None)
            if review_id:
                from baloo.agent.logger import ReviewLogger
                from baloo.config.settings import get_settings
                from baloo.db.engine import get_session_factory

                settings = get_settings()
                if settings.database_enabled:
                    factory = get_session_factory(settings.database_url)
                    logger_session = factory()
                    review_logger = ReviewLogger(review_id=review_id, session=logger_session)

            # Run agent using base class
            structured_data, metadata = await self._run_with_fallback(review_query, review_logger=review_logger)

            # Convert structured output to review comments
            comments = []
            if structured_data is not None:
                comments = findings_to_comments(structured_data)
            else:
                logger.warning(
                    "No structured output received from agent "
                    "(model: %s, turns: %s, tokens_out: %s, is_error: %s)",
                    metadata.get("model"),
                    metadata.get("num_turns"),
                    metadata.get("output_tokens"),
                    metadata.get("is_error"),
                )
                metadata["agent_error"] = True
                metadata["error_category"] = metadata.get("error_category", "no_output")

            # Generate summary using shared formatter
            summary = CommentFormatter.format_summary(comments, metadata)

            # Make approval decision using centralized engine
            approve, request_changes = DecisionEngine.make_decision(comments)

            result = ReviewResult(
                summary=summary,
                comments=comments,
                approve=approve,
                request_changes=request_changes,
                metadata=metadata,
            )

            # Flush and close the logger session
            if logger_session is not None:
                try:
                    await logger_session.commit()
                    await logger_session.close()
                except Exception:
                    pass

            return result

        except Exception as e:
            logger.error(f"Error during review: {e}", exc_info=True)
            # Return a minimal result with error info and captured metadata (costs)
            metadata = getattr(e, "metadata", {})
            metadata["agent_error"] = True
            metadata["error_category"] = self._classify_error(str(e))
            metadata["error_detail"] = str(e)
            return ReviewResult(
                summary=f"Review failed due to error: {str(e)}",
                comments=[],
                approve=False,
                request_changes=False,
                metadata=metadata,
            )

    @staticmethod
    def _classify_error(error_msg: str) -> str:
        """Classify an error message into a category for tracking."""
        msg = error_msg.lower()
        if "separator" in msg and ("chunk" in msg or "limit" in msg):
            return "buffer_overflow"
        if "prompt is too long" in msg:
            return "prompt_too_long"
        if "json" in msg and ("parse" in msg or "decode" in msg or "retry" in msg):
            return "json_parse_error"
        if "timeout" in msg or "timed out" in msg:
            return "timeout"
        if "rate limit" in msg or "429" in msg:
            return "rate_limited"
        if "authentication" in msg or "401" in msg or "403" in msg:
            return "auth_error"
        return "agent_error"

    async def _run_with_fallback(self, query: str, review_logger: Any = None):
        """Run query with automatic fallback to secondary model on failure."""
        from baloo.config.settings import get_settings

        try:
            return await self.run_query(query, review_logger=review_logger)
        except Exception as primary_err:
            settings = get_settings()
            fallback = settings.agent_fallback_model
            if not fallback or "/" not in fallback:
                raise  # No valid fallback configured

            fallback_provider, fallback_model = fallback.split("/", 1)

            # Don't fallback to the same provider/model we just failed with
            if fallback_provider == self.options.provider and fallback_model == self.options.model:
                raise

            logger.warning(
                "Primary model %s/%s failed (%s), falling back to %s",
                self.options.provider,
                self.options.model,
                primary_err,
                fallback,
            )

            if review_logger:
                await review_logger.fallback_triggered(
                    primary_model=f"{self.options.provider}/{self.options.model}",
                    fallback_model=fallback,
                    error=str(primary_err),
                )

            # Swap to fallback model
            original_provider = self.options.provider
            original_model = self.options.model
            self.options.provider = fallback_provider
            self.options.model = fallback_model

            try:
                result = await self.run_query(query, review_logger=review_logger)
                # Tag metadata so callers know fallback was used
                result[1]["fallback_used"] = True
                result[1]["primary_model"] = f"{original_provider}/{original_model}"
                result[1]["primary_error"] = str(primary_err)
                return result
            except Exception as fallback_err:
                logger.error("Fallback model %s also failed: %s", fallback, fallback_err)
                # Restore original model info on the exception metadata
                if hasattr(primary_err, "metadata"):
                    raise primary_err from fallback_err
                raise primary_err from fallback_err
            finally:
                # Restore original options
                self.options.provider = original_provider
                self.options.model = original_model
