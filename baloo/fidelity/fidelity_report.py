"""Format fidelity analysis results as markdown report."""


from baloo.fidelity.models import FidelityResult


def format_fidelity_report(
    result: FidelityResult | None = None,
    ticket_id: str | None = None,
    no_ticket: bool = False,
    no_plan: bool = False,
    plan_path: str | None = None,
) -> str:
    """
    Format fidelity analysis result as a collapsible markdown report.

    Args:
        result: FidelityResult from analysis
        ticket_id: Ticket ID (for no_plan case)
        no_ticket: True if no ticket ID was found
        no_plan: True if no plan file was found
        plan_path: Path to plan file (for no_plan case)

    Returns:
        Formatted markdown string
    """
    if no_ticket:
        return _format_no_ticket()

    if no_plan:
        return _format_no_plan(ticket_id, plan_path)

    if result is None:
        return _format_error(ticket_id)

    return _format_result(result)


def _get_score_emoji(score: int) -> str:
    """Get emoji based on fidelity score."""
    if score >= 90:
        return "\U0001f7e2"  # Green circle
    elif score >= 70:
        return "\U0001f7e1"  # Yellow circle
    else:
        return "\U0001f534"  # Red circle


def _format_result(result: FidelityResult) -> str:
    """Format a successful fidelity result."""
    emoji = _get_score_emoji(result.fidelity_score)
    score = result.fidelity_score
    ticket = result.ticket_id
    lines = [
        "<details>",
        f"<summary>\U0001f4cb Fidelity Report ({ticket}) - {emoji} {score}%</summary>",
        "",
        f"### Fidelity Score: {emoji} {score}%",
        "",
        "### Logic Summary",
        result.logic_summary,
        "",
    ]

    # Requirements checklist
    if result.requirements:
        lines.extend([
            "### Requirement Checklist",
            "| Requirement | Status | Evidence |",
            "|-------------|--------|----------|",
        ])
        for req in result.requirements:
            status_icon = _get_status_icon(req.status)
            evidence = req.evidence or "-"
            # Escape pipe characters in table cells
            description = req.description.replace("|", "\\|")
            evidence = evidence.replace("|", "\\|")
            lines.append(f"| {description} | {status_icon} | {evidence} |")
        lines.append("")

    # Hidden extras
    if result.extras:
        lines.extend([
            "### Hidden Extras",
            "_Changes implemented beyond the plan:_",
            "",
        ])
        for extra in result.extras:
            lines.append(f"- {extra}")
        lines.append("")

    # Critical discrepancies
    if result.discrepancies:
        lines.extend([
            "### Critical Discrepancies",
            "",
        ])
        for disc in result.discrepancies:
            severity_icon = _get_severity_icon(disc.severity)
            lines.append(f"- {severity_icon} **[{disc.severity}]** {disc.description}")
        lines.append("")

    lines.append("</details>")
    return "\n".join(lines)


def _get_status_icon(status: str) -> str:
    """Get icon for requirement status."""
    status_lower = status.lower()
    if status_lower == "fulfilled":
        return "\u2705 Fulfilled"  # Check mark
    elif status_lower == "partial":
        return "\u26a0\ufe0f Partial"  # Warning
    else:
        return "\u274c Missing"  # X mark


def _get_severity_icon(severity: str) -> str:
    """Get icon for discrepancy severity."""
    severity_upper = severity.upper()
    if severity_upper == "HIGH":
        return "\U0001f534"  # Red circle
    elif severity_upper == "MEDIUM":
        return "\U0001f7e1"  # Yellow circle
    else:
        return "\U0001f535"  # Blue circle


def _format_no_ticket() -> str:
    """Format report when no ticket ID is found."""
    return """<details>
<summary>\U0001f4cb Fidelity Report - \u23ed\ufe0f Skipped</summary>

**No ticket ID found in PR.**

To enable fidelity analysis:
- Use branch naming: `feat/PROJ-XXX/description` or `fix/PROJ-XXX-description`
- Or include ticket in PR title: `[PROJ-XXX] Title` or `PROJ-XXX: Title`

</details>"""


def _format_no_plan(ticket_id: str | None, plan_path: str | None) -> str:
    """Format report when no plan file is found."""
    ticket_display = ticket_id or "unknown"
    path_display = plan_path or f"docs/plans/{ticket_display}.md"

    return f"""<details>
<summary>\U0001f4cb Fidelity Report ({ticket_display}) - \u23ed\ufe0f Skipped</summary>

**No plan file found at `{path_display}`**

To enable fidelity analysis, create a plan file before implementation.

</details>"""


def _format_error(ticket_id: str | None) -> str:
    """Format report when analysis fails."""
    ticket_display = ticket_id or "unknown"

    return f"""<details>
<summary>\U0001f4cb Fidelity Report ({ticket_display}) - \u26a0\ufe0f Error</summary>

**Fidelity analysis encountered an error.**

The PR review will continue without fidelity analysis.

</details>"""
