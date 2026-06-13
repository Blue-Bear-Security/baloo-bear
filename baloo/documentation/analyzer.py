"""PI-backed documentation drift analyzer."""

from __future__ import annotations

import logging

from baloo.agent.config import get_agent_options
from baloo.agent.pi_runtime import PIAgentBase
from baloo.documentation.models import DocumentationDriftResult, DocumentationWorkItem
from baloo.documentation.prompts import (
    DOCUMENTATION_DRIFT_SYSTEM_PROMPT,
    build_documentation_drift_prompt,
)
from baloo.github.models import PRContext

logger = logging.getLogger(__name__)


class DocumentationDriftAgent(PIAgentBase):
    """Agent for PR-time documentation drift analysis."""

    def __init__(self, model: str):
        options = get_agent_options(model)
        options.system_prompt = DOCUMENTATION_DRIFT_SYSTEM_PROMPT
        options.name = "DocumentationDriftAgent"
        super().__init__(options)

    async def analyze(
        self,
        *,
        pr_context: PRContext,
        work_item: DocumentationWorkItem,
        catalog_path: str,
        repo_path: str | None,
        review_logger: object | None = None,
    ) -> DocumentationDriftResult | None:
        """Analyze a PR for documentation drift."""
        try:
            self.options.cwd = repo_path
            prompt = build_documentation_drift_prompt(
                pr_context=pr_context,
                work_item=work_item,
                catalog_path=catalog_path,
            )
            structured_data, metadata = await self.run_query(prompt, review_logger=review_logger)
            if structured_data is None:
                logger.warning("No structured output received from documentation drift agent")
                return None

            result = DocumentationDriftResult.model_validate(structured_data)
            result.metadata = metadata
            return result
        except Exception as exc:
            logger.warning("Documentation drift analysis failed: %s", exc, exc_info=True)
            return None


async def analyze_documentation_drift(
    *,
    pr_context: PRContext,
    work_item: DocumentationWorkItem,
    catalog_path: str,
    repo_path: str | None,
    model: str,
    review_logger: object | None = None,
) -> DocumentationDriftResult | None:
    """Run documentation drift analysis using a configured side agent."""
    agent = DocumentationDriftAgent(model=model)
    return await agent.analyze(
        pr_context=pr_context,
        work_item=work_item,
        catalog_path=catalog_path,
        repo_path=repo_path,
        review_logger=review_logger,
    )
