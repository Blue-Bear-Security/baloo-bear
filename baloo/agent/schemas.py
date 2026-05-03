"""Pydantic models for structured review output."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from baloo.github.models import FindingCategory, ReviewComment, ReviewSeverity

logger = logging.getLogger(__name__)

# Lookup for case-insensitive category matching
_CATEGORY_LOOKUP: dict[str, str] = {v.value.upper(): v.value for v in FindingCategory}

# Lookup for case-insensitive severity matching
_SEVERITY_LOOKUP: dict[str, str] = {v.value.upper(): v.value for v in ReviewSeverity}


def _normalize_category(raw: str) -> str:
    """Normalize a category string to match FindingCategory enum values.

    Handles uppercase ("QUALITY"), lowercase ("quality"), and title-case ("Quality").
    Falls back to "Quality" for unrecognized categories.
    """
    return _CATEGORY_LOOKUP.get(raw.upper().strip(), FindingCategory.QUALITY.value)


def _normalize_severity(raw: str) -> str:
    """Normalize a severity string to match ReviewSeverity enum values.

    Falls back to "MEDIUM" for unrecognized severities.
    """
    return _SEVERITY_LOOKUP.get(raw.upper().strip(), ReviewSeverity.MEDIUM.value)


_SEVERITY_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

# Category → minimum severity floor. Agent severity >= floor passes through;
# agent severity < floor is escalated to the floor.
# Performance is always MEDIUM; Quality is capped at MEDIUM (see enforce_severity).
_CATEGORY_MIN_SEVERITY: dict[str, str] = {
    "SECURITY": "HIGH",
    "BUGS": "HIGH",
    "SILENT FAILURES": "HIGH",
    "GUIDELINES": "HIGH",
}


class ReviewFinding(BaseModel):
    """A single review finding from the agent.

    Tolerant of agent returning unexpected types for fields.
    """

    model_config = {"extra": "ignore", "coerce_numbers_to_str": True}

    file: str = ""
    line: Any = 1
    severity: str = "MEDIUM"
    category: str = "Quality"
    title: str = "Issue"
    description: str = ""
    impact: str | None = None
    recommendation: str | None = None
    code_example: str | None = None

    def get_line(self) -> int:
        """Return line as int, with fallback to 1."""
        try:
            return max(1, int(self.line))
        except (TypeError, ValueError):
            return 1


class ReviewSummary(BaseModel):
    """Summary statistics for the review.

    All fields use ``Any`` with defaults because the agent may return
    unexpected types (e.g. a list of filenames for ``files_examined``
    instead of an int).  This model is purely informational — only used
    for logging — so strict typing is not worth the validation failures.
    """

    model_config = {"extra": "ignore"}

    total_issues: Any = 0
    critical: Any = 0
    high: Any = 0
    medium: Any = 0
    low: Any = 0
    files_examined: Any = 0
    patterns_searched: Any = Field(default_factory=list)
    positive_observations: Any = Field(default_factory=list)


class ReviewOutput(BaseModel):
    """Top-level structured output from the review agent.

    Tolerant parsing: the ``summary`` field may arrive as a dict (expected),
    a plain string (model improvised), or be missing entirely.  The validator
    coerces all of these to a ReviewSummary.
    """

    findings: list[ReviewFinding] = Field(default_factory=list)
    summary: ReviewSummary = Field(default_factory=ReviewSummary)

    @classmethod
    def model_validate(cls, obj, **kwargs):
        """Override to coerce common agent response quirks before validation."""
        if isinstance(obj, dict):
            raw_summary = obj.get("summary")
            # If the agent returned a string instead of a dict, replace with default
            if isinstance(raw_summary, str):
                obj = {**obj, "summary": {}}
            # If the agent omitted summary entirely, ensure the key exists
            elif raw_summary is None:
                obj = {**obj, "summary": {}}
        return super().model_validate(obj, **kwargs)


_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".java": "java",
    ".sh": "bash",
    ".bash": "bash",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".sql": "sql",
    ".tf": "hcl",
}


def _lang_for_file(filename: str) -> str:
    """Return the markdown language identifier for a given filename.

    Maps common file extensions to their markdown code fence language identifiers.
    Falls back to 'text' for unknown extensions.
    """
    if not filename:
        return "text"
    dot = filename.rfind(".")
    if dot == -1:
        return "text"
    ext = filename[dot:].lower()
    return _EXT_TO_LANG.get(ext, "text")


def enforce_severity(finding: ReviewFinding) -> str:
    """Derive severity from category using deterministic rules.

    Security/Bugs/Silent Failures/Guidelines → floor of HIGH (CRITICAL passes through).
    Performance → always MEDIUM (LOW escalated, HIGH/CRITICAL downgraded).
    Quality → capped at MEDIUM (keeps LOW if LOW).
    Unknown categories → MEDIUM.
    """
    category = _normalize_category(finding.category).upper()
    agent_severity = finding.severity.upper()
    agent_rank = _SEVERITY_ORDER.get(agent_severity, 2)

    # Floor semantics: escalate if agent is below floor, pass through if at/above floor
    floor = _CATEGORY_MIN_SEVERITY.get(category)
    if floor is not None:
        floor_rank = _SEVERITY_ORDER[floor]
        return agent_severity if agent_rank >= floor_rank else floor

    # Performance is always MEDIUM regardless of agent severity (LOW escalated, HIGH capped).
    if category == "PERFORMANCE":
        return "MEDIUM"

    # Quality: cap at MEDIUM, but don't escalate LOW
    if category == "QUALITY":
        cap_rank = _SEVERITY_ORDER["MEDIUM"]
        return agent_severity if agent_rank <= cap_rank else "MEDIUM"

    # Unknown category
    return "MEDIUM"


def review_output_schema() -> dict:
    """Return the JSON schema for review output validation."""
    return {"type": "json_schema", "schema": ReviewOutput.model_json_schema()}


def findings_to_comments(data: dict) -> list[ReviewComment]:
    """
    Convert a raw structured output dict into ReviewComment objects.

    Args:
        data: Dict matching the ReviewOutput schema.

    Returns:
        List of ReviewComment objects.
    """
    output = ReviewOutput.model_validate(data)

    if output.summary:
        logger.info(
            "Agent Tool Usage Summary:\n"
            "  - Total issues: %s\n"
            "  - Critical: %s\n"
            "  - High: %s\n"
            "  - Medium: %s\n"
            "  - Low: %s\n"
            "  - Files examined: %s\n"
            "  - Patterns searched: %s\n"
            "  - Positive observations: %s",
            output.summary.total_issues or len(output.findings),
            output.summary.critical,
            output.summary.high,
            output.summary.medium,
            output.summary.low,
            output.summary.files_examined or "N/A",
            output.summary.patterns_searched,
            output.summary.positive_observations,
        )

    comments: list[ReviewComment] = []
    for finding in output.findings:
        enforced_severity = enforce_severity(finding)
        body_parts = [
            f"**{finding.title}**",
            f"**Category:** {finding.category}",
            f"**Severity:** {enforced_severity}",
            "",
            finding.description,
        ]

        if finding.impact:
            body_parts.extend(["", f"**Impact:** {finding.impact}"])

        if finding.recommendation:
            body_parts.extend(["", "**Recommendation:**", finding.recommendation])

        if finding.code_example:
            lang = _lang_for_file(finding.file)
            body_parts.extend(["", f"```{lang}", finding.code_example, "```"])
        comments.append(
            ReviewComment(
                path=finding.file or "unknown",
                line=finding.get_line(),
                body="\n".join(body_parts),
                severity=_normalize_severity(enforced_severity),
                category=_normalize_category(finding.category),
            )
        )

    return comments
