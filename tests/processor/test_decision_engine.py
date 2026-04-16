"""Tests for decision engine module."""

from unittest.mock import patch

from baloo.fidelity.models import FidelityResult
from baloo.github.models import ReviewComment
from baloo.processor.decision_engine import DecisionEngine


def _make_comment(severity: str, category: str = "Quality") -> ReviewComment:
    """Helper to create a ReviewComment with given severity."""
    return ReviewComment(
        path="test.py",
        line=1,
        body=f"{severity} issue",
        severity=severity,
        category=category,
    )


def _make_fidelity_result(score: int) -> FidelityResult:
    """Helper to create a FidelityResult with given score."""
    return FidelityResult(
        ticket_id="DEN-123",
        fidelity_score=score,
        logic_summary="Test implementation summary",
        requirements=[],
        extras=[],
        discrepancies=[],
    )


class TestMakeDecisionWithoutFidelity:
    """Tests for make_decision without fidelity result (existing behavior)."""

    def test_no_comments_with_auto_approve_enabled(self):
        """Empty comments list with auto_approve should approve."""
        with patch("baloo.config.settings.settings.review_auto_approve", True):
            approve, request_changes = DecisionEngine.make_decision([])
            assert approve is True
            assert request_changes is False

    def test_no_comments_with_auto_approve_disabled(self):
        """Empty comments list without auto_approve should not approve."""
        with patch("baloo.config.settings.settings.review_auto_approve", False):
            approve, request_changes = DecisionEngine.make_decision([])
            assert approve is False
            assert request_changes is False

    def test_critical_issues_request_changes(self):
        """CRITICAL issues should request changes."""
        comments = [_make_comment("CRITICAL")]
        approve, request_changes = DecisionEngine.make_decision(comments)
        assert approve is False
        assert request_changes is True

    def test_high_issues_request_changes(self):
        """HIGH issues should request changes."""
        comments = [_make_comment("HIGH")]
        approve, request_changes = DecisionEngine.make_decision(comments)
        assert approve is False
        assert request_changes is True

    def test_medium_issues_no_blocking(self):
        """MEDIUM issues should not block (comments only)."""
        comments = [_make_comment("MEDIUM")]
        with patch("baloo.config.settings.settings.review_auto_approve", False):
            approve, request_changes = DecisionEngine.make_decision(comments)
            assert approve is False
            assert request_changes is False

    def test_low_issues_no_blocking(self):
        """LOW issues should not block (comments only)."""
        comments = [_make_comment("LOW")]
        with patch("baloo.config.settings.settings.review_auto_approve", False):
            approve, request_changes = DecisionEngine.make_decision(comments)
            assert approve is False
            assert request_changes is False


class TestMakeDecisionWithFidelity:
    """Tests for make_decision with fidelity result (new feature)."""

    def test_clean_review_high_fidelity_approves(self):
        """Clean review (no HIGH/MEDIUM) with high fidelity should approve."""
        comments = []  # No issues
        fidelity = _make_fidelity_result(95)

        with patch("baloo.config.settings.settings.fidelity_approval_threshold", 90):
            approve, request_changes = DecisionEngine.make_decision(
                comments, fidelity_result=fidelity
            )
            assert approve is True
            assert request_changes is False

    def test_clean_review_with_low_issues_high_fidelity_approves(self):
        """Clean review with only LOW issues and high fidelity should approve."""
        comments = [_make_comment("LOW"), _make_comment("LOW")]
        fidelity = _make_fidelity_result(92)

        with patch("baloo.config.settings.settings.fidelity_approval_threshold", 90):
            approve, request_changes = DecisionEngine.make_decision(
                comments, fidelity_result=fidelity
            )
            assert approve is True
            assert request_changes is False

    def test_medium_issues_high_fidelity_approves(self):
        """MEDIUM issues should NOT prevent fidelity-based approval."""
        comments = [_make_comment("MEDIUM")]
        fidelity = _make_fidelity_result(95)

        with patch("baloo.config.settings.settings.fidelity_approval_threshold", 90):
            approve, request_changes = DecisionEngine.make_decision(
                comments, fidelity_result=fidelity
            )
            assert approve is True
            assert request_changes is False

    def test_high_issues_high_fidelity_requests_changes(self):
        """HIGH issues should still request changes despite high fidelity."""
        comments = [_make_comment("HIGH")]
        fidelity = _make_fidelity_result(95)

        with patch("baloo.config.settings.settings.fidelity_approval_threshold", 90):
            approve, request_changes = DecisionEngine.make_decision(
                comments, fidelity_result=fidelity
            )
            assert approve is False
            assert request_changes is True

    def test_critical_issues_high_fidelity_requests_changes(self):
        """CRITICAL issues should still request changes despite high fidelity."""
        comments = [_make_comment("CRITICAL")]
        fidelity = _make_fidelity_result(100)

        with patch("baloo.config.settings.settings.fidelity_approval_threshold", 90):
            approve, request_changes = DecisionEngine.make_decision(
                comments, fidelity_result=fidelity
            )
            assert approve is False
            assert request_changes is True

    def test_clean_review_low_fidelity_no_auto_approve(self):
        """Clean review with low fidelity should not auto-approve."""
        comments = []
        fidelity = _make_fidelity_result(70)  # Below threshold

        with (
            patch("baloo.config.settings.settings.fidelity_approval_threshold", 90),
            patch("baloo.config.settings.settings.review_auto_approve", False),
        ):
            approve, request_changes = DecisionEngine.make_decision(
                comments, fidelity_result=fidelity
            )
            assert approve is False
            assert request_changes is False

    def test_clean_review_fidelity_at_threshold_approves(self):
        """Clean review with fidelity exactly at threshold should approve."""
        comments = []
        fidelity = _make_fidelity_result(90)  # Exactly at threshold

        with patch("baloo.config.settings.settings.fidelity_approval_threshold", 90):
            approve, request_changes = DecisionEngine.make_decision(
                comments, fidelity_result=fidelity
            )
            assert approve is True
            assert request_changes is False

    def test_clean_review_fidelity_below_threshold_uses_auto_approve(self):
        """Clean review with fidelity below threshold falls back to auto_approve."""
        comments = []
        fidelity = _make_fidelity_result(89)  # Just below threshold

        with (
            patch("baloo.config.settings.settings.fidelity_approval_threshold", 90),
            patch("baloo.config.settings.settings.review_auto_approve", True),
        ):
            approve, request_changes = DecisionEngine.make_decision(
                comments, fidelity_result=fidelity
            )
            # Falls back to auto_approve setting
            assert approve is True
            assert request_changes is False

    def test_no_fidelity_result_uses_auto_approve(self):
        """Without fidelity result, should use existing auto_approve logic."""
        comments = []

        with patch("baloo.config.settings.settings.review_auto_approve", True):
            approve, request_changes = DecisionEngine.make_decision(comments, fidelity_result=None)
            assert approve is True
            assert request_changes is False

    def test_mixed_severity_with_high_fidelity(self):
        """Mixed severities: HIGH should still block even with high fidelity."""
        comments = [
            _make_comment("LOW"),
            _make_comment("MEDIUM"),
            _make_comment("HIGH"),
        ]
        fidelity = _make_fidelity_result(98)

        with patch("baloo.config.settings.settings.fidelity_approval_threshold", 90):
            approve, request_changes = DecisionEngine.make_decision(
                comments, fidelity_result=fidelity
            )
            assert approve is False
            assert request_changes is True


class TestGetDecisionSummary:
    """Tests for get_decision_summary helper."""

    def test_approved_summary(self):
        """Approved decision should have appropriate summary."""
        summary = DecisionEngine.get_decision_summary(approve=True, request_changes=False)
        assert "Approved" in summary
        assert "✅" in summary

    def test_request_changes_summary(self):
        """Request changes decision should have appropriate summary."""
        summary = DecisionEngine.get_decision_summary(approve=False, request_changes=True)
        assert "Changes Requested" in summary
        assert "❌" in summary

    def test_comments_only_summary(self):
        """Comments only decision should have appropriate summary."""
        summary = DecisionEngine.get_decision_summary(approve=False, request_changes=False)
        assert "Comments Only" in summary
        assert "💬" in summary
