"""Tests for severity router module."""

from baloo.github.models import ReviewComment
from baloo.processor.severity_router import route_findings


def test_route_findings_splits_by_severity():
    """Test that findings are correctly routed by severity."""
    findings = [
        ReviewComment(
            path="a.py", line=1, body="Critical security issue",
            severity="CRITICAL", category="Security"
        ),
        ReviewComment(
            path="b.py", line=2, body="High priority bug",
            severity="HIGH", category="Bugs"
        ),
        ReviewComment(
            path="c.py", line=3, body="Medium quality issue",
            severity="MEDIUM", category="Quality"
        ),
        ReviewComment(
            path="d.py", line=4, body="Medium performance issue",
            severity="MEDIUM", category="Performance"
        ),
        ReviewComment(
            path="e.py", line=5, body="Low style issue",
            severity="LOW", category="Quality"
        ),
    ]

    routed = route_findings(findings)

    # CRITICAL and HIGH go to review
    assert len(routed["review"]) == 2
    assert routed["review"][0].severity == "CRITICAL"
    assert routed["review"][1].severity == "HIGH"

    # MEDIUM goes to checks
    assert len(routed["checks"]) == 2
    assert all(f.severity == "MEDIUM" for f in routed["checks"])

    # LOW is silently ignored (not in either bucket)
    assert len(routed["review"]) + len(routed["checks"]) == 4


def test_route_findings_empty_list():
    """Test routing with empty findings list."""
    routed = route_findings([])

    assert routed["review"] == []
    assert routed["checks"] == []


def test_route_findings_only_critical():
    """Test routing with only CRITICAL findings."""
    findings = [
        ReviewComment(
            path="a.py", line=1, body="Critical issue 1",
            severity="CRITICAL", category="Security"
        ),
        ReviewComment(
            path="b.py", line=2, body="Critical issue 2",
            severity="CRITICAL", category="Security"
        ),
    ]

    routed = route_findings(findings)

    assert len(routed["review"]) == 2
    assert len(routed["checks"]) == 0


def test_route_findings_only_medium():
    """Test routing with only MEDIUM findings."""
    findings = [
        ReviewComment(
            path="a.py", line=1, body="Medium issue 1",
            severity="MEDIUM", category="Quality"
        ),
        ReviewComment(
            path="b.py", line=2, body="Medium issue 2",
            severity="MEDIUM", category="Performance"
        ),
    ]

    routed = route_findings(findings)

    assert len(routed["review"]) == 0
    assert len(routed["checks"]) == 2


def test_route_findings_preserves_finding_data():
    """Test that routing preserves all finding data."""
    finding = ReviewComment(
        path="test.py",
        line=42,
        body="Test issue with detailed description",
        severity="HIGH",
        category="Bugs"
    )

    routed = route_findings([finding])

    routed_finding = routed["review"][0]
    assert routed_finding.path == "test.py"
    assert routed_finding.line == 42
    assert routed_finding.body == "Test issue with detailed description"
    assert routed_finding.severity == "HIGH"
    assert routed_finding.category == "Bugs"
