"""Markdown reporting helpers for documentation drift analysis."""

from __future__ import annotations

from baloo.documentation.models import DocumentationDriftFinding, DocumentationDriftResult

DOCUMENTATION_DRIFT_SENTINEL = "<!-- baloo:documentation-drift-report -->"


def format_documentation_drift_report(result: DocumentationDriftResult) -> str:
    """Format a single PR-level documentation drift report."""
    lines = [
        DOCUMENTATION_DRIFT_SENTINEL,
        "",
        "## Documentation Drift Review",
        "",
    ]

    if not has_reportable_documentation_drift(result):
        lines.append("Action required: none.")
        lines.append("")
        lines.append("No documentation drift detected in the latest review.")
        return "\n".join(lines).rstrip() + "\n"

    lines.extend([_format_action_required(result), ""])

    summary = (
        result.summary
        or "This PR appears to change behavior or workflows that are documented elsewhere."
    )
    summary = _strip_action_prefix(summary)
    if summary:
        lines.extend([summary, ""])

    if result.required_updates:
        lines.extend(["### Required Updates", ""])
        lines.extend(_format_findings(result.required_updates))
        lines.append("")

    if result.optional_updates:
        lines.extend(["### Optional Updates", ""])
        lines.extend(_format_findings(result.optional_updates))
        lines.append("")

    if result.catalog_gaps:
        lines.extend(["### Catalog Hygiene", ""])
        for gap in result.catalog_gaps:
            lines.append(
                f"- `{gap}` is not mapped. Add a catalog rule if this area "
                "should be checked for documentation drift, or mark it read-only if it should "
                "never request docs."
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def has_documentation_drift_comment(body: str) -> bool:
    """Return True when a comment body is a documentation drift report."""
    return DOCUMENTATION_DRIFT_SENTINEL in body


def has_actionable_documentation_drift(result: DocumentationDriftResult) -> bool:
    """Return True when a result should create or keep a PR comment."""
    return bool(result.required_updates or result.catalog_gaps)


def has_reportable_documentation_drift(result: DocumentationDriftResult) -> bool:
    """Return True when a documentation drift result is useful enough to show."""
    return bool(result.required_updates or result.catalog_gaps)


def _format_action_required(result: DocumentationDriftResult) -> str:
    if result.required_updates:
        return "Action required: update docs."
    return "Action required: none."


def _strip_action_prefix(summary: str) -> str:
    stripped = summary.strip()
    lowered = stripped.lower()
    for prefix in (
        "action required: none.",
        "action required: none",
        "action required: update docs.",
        "action required: update docs",
    ):
        if lowered.startswith(prefix):
            return stripped[len(prefix) :].lstrip(" \n:-")
    return stripped


def _format_findings(findings: list[DocumentationDriftFinding]) -> list[str]:
    lines: list[str] = []
    for finding in findings:
        lines.append(f"- `{finding.doc_path}`")
        if finding.suggested_update:
            lines.append(f"  - {finding.suggested_update}")
        lines.append(f"  - Rationale: {finding.rationale}")
        if finding.evidence:
            evidence = ", ".join(f"`{item}`" for item in finding.evidence)
            lines.append(f"  - Evidence: {evidence}")
    return lines
