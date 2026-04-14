"""Tests for fidelity report formatting."""

import pytest

from baloo.fidelity.fidelity_analyzer import FidelityAgent
from baloo.fidelity.fidelity_report import (
    _get_score_emoji,
    _get_severity_icon,
    _get_status_icon,
    format_fidelity_report,
)
from baloo.fidelity.models import Discrepancy, FidelityResult, Requirement


class TestGetScoreEmoji:
    """Tests for _get_score_emoji function."""

    def test_green_for_90_plus(self):
        """Test green emoji for scores >= 90."""
        assert _get_score_emoji(90) == "\U0001f7e2"
        assert _get_score_emoji(95) == "\U0001f7e2"
        assert _get_score_emoji(100) == "\U0001f7e2"

    def test_yellow_for_70_to_89(self):
        """Test yellow emoji for scores 70-89."""
        assert _get_score_emoji(70) == "\U0001f7e1"
        assert _get_score_emoji(80) == "\U0001f7e1"
        assert _get_score_emoji(89) == "\U0001f7e1"

    def test_red_for_below_70(self):
        """Test red emoji for scores < 70."""
        assert _get_score_emoji(69) == "\U0001f534"
        assert _get_score_emoji(50) == "\U0001f534"
        assert _get_score_emoji(0) == "\U0001f534"


class TestGetStatusIcon:
    """Tests for _get_status_icon function."""

    def test_fulfilled_status(self):
        """Test icon for fulfilled status."""
        assert "Fulfilled" in _get_status_icon("fulfilled")
        assert "\u2705" in _get_status_icon("fulfilled")

    def test_partial_status(self):
        """Test icon for partial status."""
        assert "Partial" in _get_status_icon("partial")
        assert "\u26a0" in _get_status_icon("partial")

    def test_missing_status(self):
        """Test icon for missing status."""
        assert "Missing" in _get_status_icon("missing")
        assert "\u274c" in _get_status_icon("missing")

    def test_case_insensitive(self):
        """Test that status check is case-insensitive."""
        assert "Fulfilled" in _get_status_icon("FULFILLED")
        assert "Partial" in _get_status_icon("PARTIAL")


class TestGetSeverityIcon:
    """Tests for _get_severity_icon function."""

    def test_high_severity(self):
        """Test red icon for HIGH severity."""
        assert _get_severity_icon("HIGH") == "\U0001f534"

    def test_medium_severity(self):
        """Test yellow icon for MEDIUM severity."""
        assert _get_severity_icon("MEDIUM") == "\U0001f7e1"

    def test_low_severity(self):
        """Test blue icon for LOW severity."""
        assert _get_severity_icon("LOW") == "\U0001f535"

    def test_case_insensitive(self):
        """Test that severity check is case-insensitive."""
        assert _get_severity_icon("high") == "\U0001f534"
        assert _get_severity_icon("Medium") == "\U0001f7e1"


class TestFidelityAgentOptions:
    """Tests for FidelityAgent options."""

    def test_uses_sonnet_model(self):
        """Fidelity analyzer must use Sonnet for thorough analysis."""
        agent = FidelityAgent()
        assert agent.options.model == "claude-sonnet-4-6"


class TestFormatFidelityReportNoTicket:
    """Tests for format_fidelity_report with no_ticket=True."""

    def test_no_ticket_format(self):
        """Test formatting when no ticket ID is found."""
        report = format_fidelity_report(no_ticket=True)

        assert "<details>" in report
        assert "</details>" in report
        assert "Fidelity Report" in report
        assert "Skipped" in report
        assert "No ticket ID found" in report
        assert "feat/PROJ-XXX" in report
        assert "[PROJ-XXX]" in report


class TestFormatFidelityReportNoPlan:
    """Tests for format_fidelity_report with no_plan=True."""

    def test_no_plan_format(self):
        """Test formatting when no plan file is found."""
        report = format_fidelity_report(
            no_plan=True,
            ticket_id="DEN-123",
            plan_path="docs/plans/DEN-123.md",
        )

        assert "<details>" in report
        assert "</details>" in report
        assert "Fidelity Report" in report
        assert "DEN-123" in report
        assert "Skipped" in report
        assert "No plan file found" in report
        assert "docs/plans/DEN-123.md" in report


class TestFormatFidelityReportSuccess:
    """Tests for format_fidelity_report with successful result."""

    @pytest.fixture
    def high_score_result(self) -> FidelityResult:
        """Create a high-score fidelity result."""
        return FidelityResult(
            ticket_id="DEN-123",
            fidelity_score=95,
            logic_summary=(
                "The implementation adds a new authentication endpoint. "
                "It follows the plan closely."
            ),
            requirements=[
                Requirement(
                    description="Add login endpoint",
                    status="fulfilled",
                    evidence="Implemented in src/auth.py:42",
                ),
                Requirement(
                    description="Add logout endpoint",
                    status="fulfilled",
                    evidence="Implemented in src/auth.py:78",
                ),
            ],
            extras=["Added logging"],
            discrepancies=[],
        )

    @pytest.fixture
    def low_score_result(self) -> FidelityResult:
        """Create a low-score fidelity result."""
        return FidelityResult(
            ticket_id="DEN-456",
            fidelity_score=55,
            logic_summary="Partial implementation. Missing key features.",
            requirements=[
                Requirement(
                    description="Feature A",
                    status="fulfilled",
                    evidence="src/a.py",
                ),
                Requirement(
                    description="Feature B",
                    status="missing",
                    evidence=None,
                ),
                Requirement(
                    description="Feature C",
                    status="partial",
                    evidence="Started in src/c.py but incomplete",
                ),
            ],
            extras=["Unplanned refactoring"],
            discrepancies=[
                Discrepancy(
                    description="Used different approach for auth",
                    severity="HIGH",
                ),
                Discrepancy(
                    description="Minor naming differences",
                    severity="LOW",
                ),
            ],
        )

    def test_high_score_has_green_emoji(self, high_score_result):
        """Test that high scores show green emoji."""
        report = format_fidelity_report(result=high_score_result)

        assert "\U0001f7e2" in report  # Green circle
        assert "95%" in report

    def test_low_score_has_red_emoji(self, low_score_result):
        """Test that low scores show red emoji."""
        report = format_fidelity_report(result=low_score_result)

        assert "\U0001f534" in report  # Red circle
        assert "55%" in report

    def test_contains_logic_summary(self, high_score_result):
        """Test that report contains logic summary."""
        report = format_fidelity_report(result=high_score_result)

        assert "Logic Summary" in report
        assert high_score_result.logic_summary in report

    def test_contains_requirements_table(self, high_score_result):
        """Test that report contains requirements checklist table."""
        report = format_fidelity_report(result=high_score_result)

        assert "Requirement Checklist" in report
        assert "| Requirement | Status | Evidence |" in report
        assert "Add login endpoint" in report
        assert "Add logout endpoint" in report
        assert "Fulfilled" in report

    def test_contains_extras_section(self, high_score_result):
        """Test that report contains extras section when present."""
        report = format_fidelity_report(result=high_score_result)

        assert "Hidden Extras" in report
        assert "Added logging" in report

    def test_contains_discrepancies_section(self, low_score_result):
        """Test that report contains discrepancies section when present."""
        report = format_fidelity_report(result=low_score_result)

        assert "Critical Discrepancies" in report
        assert "Used different approach for auth" in report
        assert "[HIGH]" in report
        assert "[LOW]" in report

    def test_collapsible_details(self, high_score_result):
        """Test that report uses collapsible HTML details."""
        report = format_fidelity_report(result=high_score_result)

        assert "<details>" in report
        assert "</details>" in report
        assert "<summary>" in report
        assert "</summary>" in report

    def test_no_extras_section_when_empty(self):
        """Test that extras section is omitted when empty."""
        result = FidelityResult(
            ticket_id="DEN-789",
            fidelity_score=100,
            logic_summary="Perfect match.",
            requirements=[],
            extras=[],
            discrepancies=[],
        )
        report = format_fidelity_report(result=result)

        assert "Hidden Extras" not in report

    def test_no_discrepancies_section_when_empty(self):
        """Test that discrepancies section is omitted when empty."""
        result = FidelityResult(
            ticket_id="DEN-789",
            fidelity_score=100,
            logic_summary="Perfect match.",
            requirements=[],
            extras=[],
            discrepancies=[],
        )
        report = format_fidelity_report(result=result)

        assert "Critical Discrepancies" not in report


class TestFormatFidelityReportError:
    """Tests for format_fidelity_report with None result (error case)."""

    def test_error_format(self):
        """Test formatting when analysis fails (result=None)."""
        report = format_fidelity_report(result=None, ticket_id="DEN-123")

        assert "<details>" in report
        assert "</details>" in report
        assert "Fidelity Report" in report
        assert "DEN-123" in report
        assert "Error" in report
        assert "encountered an error" in report
