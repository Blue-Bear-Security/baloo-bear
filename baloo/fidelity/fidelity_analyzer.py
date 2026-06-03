"""Fidelity analyzer using PI agent."""

import logging

from baloo.agent.pi_runtime import PIAgentBase, PIAgentOptions
from baloo.fidelity.models import (
    FidelityOutput,
    FidelityResult,
    FidelitySpec,
)
from baloo.fidelity.prompts import FIDELITY_SYSTEM_PROMPT, build_fidelity_prompt

logger = logging.getLogger(__name__)


class FidelityAgent(PIAgentBase):
    """Agent for fidelity analysis comparing PR changes to design spec."""

    def __init__(self):
        options = PIAgentOptions(
            model="claude-sonnet-4-6",
            provider="anthropic",
            system_prompt=FIDELITY_SYSTEM_PROMPT,
            thinking_level="medium",
            max_turns=20,
        )
        super().__init__(options)

    async def analyze(
        self,
        spec: FidelitySpec,
        pr_title: str,
        diff: str,
        ticket_id: str,
    ) -> FidelityResult | None:
        """
        Run fidelity analysis comparing PR changes to design spec.

        Args:
            spec: FidelitySpec with ticket and plan layers
            pr_title: PR title for context
            diff: The PR diff
            ticket_id: Ticket ID (e.g., PROJ-123)

        Returns:
            FidelityResult with analysis, or None if analysis fails
        """
        logger.info(f"Starting fidelity analysis for {ticket_id}")

        try:
            prompt = build_fidelity_prompt(spec, pr_title, diff)
            structured_data, metadata = await self.run_query(prompt)
            result = self._parse_structured_fidelity(structured_data, ticket_id)

            if result:
                result.metadata = metadata
                logger.info(
                    f"Fidelity result for {ticket_id}: "
                    f"score={result.fidelity_score}%, "
                    f"requirements={len(result.requirements)}, "
                    f"discrepancies={len(result.discrepancies)}"
                )

            return result

        except Exception as e:
            logger.error(f"Fidelity analysis failed for {ticket_id}: {e}", exc_info=True)
            return None

    def _parse_structured_fidelity(
        self, data: dict | None, ticket_id: str
    ) -> FidelityResult | None:
        if data is None:
            logger.warning("No structured output received from fidelity agent")
            return None

        try:
            output = FidelityOutput.model_validate(data)
            return FidelityResult(
                ticket_id=ticket_id,
                fidelity_score=output.fidelity_score,
                logic_summary=output.logic_summary,
                requirements=output.requirements,
                extras=output.extras,
                discrepancies=output.discrepancies,
            )
        except Exception as e:
            logger.warning(f"Error parsing fidelity structured output: {e}")
            return None


async def analyze_fidelity(
    spec: FidelitySpec,
    pr_title: str,
    diff: str,
    ticket_id: str,
) -> FidelityResult | None:
    """Run fidelity analysis via FidelityAgent."""
    agent = FidelityAgent()
    return await agent.analyze(spec, pr_title, diff, ticket_id)
