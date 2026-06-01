"""Tests for FidelityAgent and analyze_fidelity wrapper."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


class TestFidelityAgentAnalyze:
    @pytest.mark.asyncio
    async def test_successful_analysis_returns_result(self):
        from baloo.fidelity.fidelity_analyzer import FidelityAgent
        from baloo.fidelity.models import FidelitySpec

        structured_data = {
            "fidelity_score": 85,
            "logic_summary": "The PR matches the plan.",
            "requirements": [],
            "extras": [],
            "discrepancies": [],
        }
        mock_metadata = {"cost_usd": 0.01, "input_tokens": 100, "output_tokens": 50}

        agent = FidelityAgent()
        spec = FidelitySpec(ticket=None, plan="# Plan\n- Do X")
        with patch.object(
            agent, "run_query", new=AsyncMock(return_value=(structured_data, mock_metadata))
        ):
            result = await agent.analyze(
                spec=spec,
                pr_title="Implement feature X",
                diff="+ added code",
                ticket_id="PROJ-123",
            )

        assert result is not None
        assert result.fidelity_score == 85
        assert result.ticket_id == "PROJ-123"
        assert result.metadata == mock_metadata

    @pytest.mark.asyncio
    async def test_run_query_exception_returns_none(self):
        from baloo.fidelity.fidelity_analyzer import FidelityAgent
        from baloo.fidelity.models import FidelitySpec

        agent = FidelityAgent()
        spec = FidelitySpec(ticket=None, plan="# Plan")
        with patch.object(
            agent, "run_query", new=AsyncMock(side_effect=RuntimeError("agent crashed"))
        ):
            result = await agent.analyze(
                spec=spec,
                pr_title="Test PR",
                diff="+ code",
                ticket_id="PROJ-456",
            )

        assert result is None


class TestParseStructuredFidelity:
    def test_none_data_returns_none(self):
        from baloo.fidelity.fidelity_analyzer import FidelityAgent

        agent = FidelityAgent()
        result = agent._parse_structured_fidelity(None, "PROJ-001")
        assert result is None

    def test_invalid_data_returns_none(self):
        from baloo.fidelity.fidelity_analyzer import FidelityAgent

        agent = FidelityAgent()
        # fidelity_score must be an int; a non-coercible value triggers a Pydantic error
        result = agent._parse_structured_fidelity({"fidelity_score": "not-a-number"}, "PROJ-002")
        assert result is None

    def test_valid_data_returns_result(self):
        from baloo.fidelity.fidelity_analyzer import FidelityAgent

        agent = FidelityAgent()
        data = {
            "fidelity_score": 90,
            "logic_summary": "Matches plan.",
            "requirements": [],
            "extras": [],
            "discrepancies": [],
        }
        result = agent._parse_structured_fidelity(data, "PROJ-003")
        assert result is not None
        assert result.fidelity_score == 90
        assert result.ticket_id == "PROJ-003"


class TestAnalyzeFidelityWrapper:
    @pytest.mark.asyncio
    async def test_wrapper_delegates_to_agent(self):
        from baloo.fidelity.fidelity_analyzer import analyze_fidelity
        from baloo.fidelity.models import FidelitySpec

        structured_data = {
            "fidelity_score": 75,
            "logic_summary": "Partial match.",
            "requirements": [],
            "extras": [],
            "discrepancies": [],
        }

        spec = FidelitySpec(ticket=None, plan="# Plan")
        with patch(
            "baloo.fidelity.fidelity_analyzer.FidelityAgent.run_query",
            new=AsyncMock(return_value=(structured_data, {})),
        ):
            result = await analyze_fidelity(
                spec=spec,
                pr_title="Test",
                diff="+ code",
                ticket_id="PROJ-789",
            )

        assert result is not None
        assert result.ticket_id == "PROJ-789"
