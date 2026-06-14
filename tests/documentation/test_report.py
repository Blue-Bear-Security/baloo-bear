"""Tests for documentation drift report formatting."""

from baloo.documentation.models import DocumentationDriftFinding, DocumentationDriftResult
from baloo.documentation.report import (
    DOCUMENTATION_DRIFT_SENTINEL,
    format_documentation_drift_report,
    has_actionable_documentation_drift,
    has_documentation_drift_comment,
)


def test_report_includes_sentinel():
    body = format_documentation_drift_report(
        DocumentationDriftResult(
            required_updates=[
                DocumentationDriftFinding(
                    doc_path="README.md",
                    verdict="required",
                    rationale="Behavior changed.",
                )
            ]
        )
    )

    assert body.startswith(DOCUMENTATION_DRIFT_SENTINEL)
    assert has_documentation_drift_comment(body)


def test_required_updates_render_before_optional_updates():
    body = format_documentation_drift_report(
        DocumentationDriftResult(
            required_updates=[
                DocumentationDriftFinding(
                    doc_path="README.md",
                    verdict="required",
                    rationale="Required rationale.",
                )
            ],
            optional_updates=[
                DocumentationDriftFinding(
                    doc_path="docs/features/models.md",
                    verdict="optional",
                    rationale="Optional rationale.",
                )
            ],
        )
    )

    assert body.index("### Required Updates") < body.index("### Optional Updates")


def test_empty_result_renders_no_drift_message():
    body = format_documentation_drift_report(DocumentationDriftResult())

    assert "Action required: none." in body
    assert "No documentation drift detected in the latest review." in body


def test_report_suppresses_already_covered_section():
    body = format_documentation_drift_report(
        DocumentationDriftResult(
            catalog_gaps=["baloo/documentation/analyzer.py"],
            not_needed=[
                DocumentationDriftFinding(
                    doc_path="README.md",
                    verdict="not_needed",
                    rationale="Already generic enough.",
                )
            ],
        )
    )

    assert "### Already Covered" not in body
    assert "README.md" not in body


def test_catalog_gaps_render_as_catalog_hygiene():
    body = format_documentation_drift_report(
        DocumentationDriftResult(catalog_gaps=["baloo/documentation/analyzer.py"])
    )

    assert "Action required: none." in body
    assert "### Catalog Hygiene" in body
    assert "Add a catalog rule" in body
    assert "### Catalog Gaps" not in body


def test_required_updates_render_action_required():
    body = format_documentation_drift_report(
        DocumentationDriftResult(
            summary="Action required: update docs. API response changed.",
            required_updates=[
                DocumentationDriftFinding(
                    doc_path="docs/api.md",
                    verdict="required",
                    rationale="Response shape changed.",
                )
            ],
        )
    )

    assert body.count("Action required: update docs.") == 1
    assert "API response changed." in body


def test_has_actionable_documentation_drift_for_required_updates_or_gaps():
    assert has_actionable_documentation_drift(
        DocumentationDriftResult(
            required_updates=[
                DocumentationDriftFinding(
                    doc_path="README.md",
                    verdict="required",
                    rationale="Required.",
                )
            ]
        )
    )
    assert has_actionable_documentation_drift(
        DocumentationDriftResult(catalog_gaps=["baloo/documentation/** is unmapped"])
    )
    assert not has_actionable_documentation_drift(DocumentationDriftResult())
