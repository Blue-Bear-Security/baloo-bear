"""Route review findings by severity and provide counting utilities."""

from baloo.github.models import ReviewComment, ReviewSeverity


def count_by_severity(findings: list[ReviewComment]) -> dict[str, int]:
    """
    Count findings by their severity level.

    Args:
        findings: List of review comments

    Returns:
        Dictionary mapping severity names to counts
    """
    counts = {s.value: 0 for s in ReviewSeverity}
    for finding in findings:
        severity = finding.severity.upper()
        if severity in counts:
            counts[severity] += 1
        else:
            # Handle unknown severities as MEDIUM
            counts[ReviewSeverity.MEDIUM.value] += 1
    return counts


def route_findings(findings: list[ReviewComment]) -> dict:
    """
    Split findings by reporting method based on severity.

    CRITICAL/HIGH findings are blocking and should be posted as PR review comments.
    MEDIUM findings are non-blocking and should be posted as GitHub Checks.
    LOW findings are typically for information only.

    Args:
        findings: List of review comments from the agent

    Returns:
        Dictionary with keys:
        - "review": List of CRITICAL/HIGH findings (blocking, PR review comments)
        - "checks": List of MEDIUM findings (non-blocking, GitHub Checks)
    """
    review_findings = []
    checks_findings = []

    for finding in findings:
        severity = finding.severity.upper()
        if severity in [ReviewSeverity.CRITICAL.value, ReviewSeverity.HIGH.value]:
            review_findings.append(finding)
        elif severity == ReviewSeverity.MEDIUM.value:
            checks_findings.append(finding)
        # LOW severity is currently not routed to a specific GitHub reporting mechanism
        # but could be added to the digest.

    return {"review": review_findings, "checks": checks_findings}
