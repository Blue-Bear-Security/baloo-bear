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

    if not has_actionable_documentation_drift(result) and not result.optional_updates:
        lines.append("No documentation drift detected in the latest review.")
        return "\n".join(lines).rstrip() + "\n"

    summary = (
        result.summary
        or "This PR appears to change behavior or workflows that are documented elsewhere."
    )
    lines.extend([summary, ""])

    if result.required_updates:
        lines.extend(["### Required Updates", ""])
        lines.extend(_format_findings(result.required_updates))
        lines.append("")

    if result.optional_updates:
        lines.extend(["### Optional Updates", ""])
        lines.extend(_format_findings(result.optional_updates))
        lines.append("")

    if result.not_needed:
        lines.extend(["### Already Covered", ""])
        lines.extend(_format_findings(result.not_needed))
        lines.append("")

    if result.catalog_gaps:
        lines.extend(["### Catalog Gaps", ""])
        for gap in result.catalog_gaps:
            lines.append(f"- `{gap}` is not mapped in the documentation drift catalog.")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def has_documentation_drift_comment(body: str) -> bool:
    """Return True when a comment body is a documentation drift report."""
    return DOCUMENTATION_DRIFT_SENTINEL in body


def has_actionable_documentation_drift(result: DocumentationDriftResult) -> bool:
    """Return True when a result should create or keep a PR comment."""
    return bool(result.required_updates or result.catalog_gaps)


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
