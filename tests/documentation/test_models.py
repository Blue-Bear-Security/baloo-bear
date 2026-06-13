"""Tests for documentation drift data models."""

import pytest
from pydantic import ValidationError

from baloo.documentation.models import (
    DocumentationCatalog,
    DocumentationCatalogRule,
    DocumentationDriftFinding,
    DocumentationDriftResult,
    DocumentationWorkItem,
    DocumentationWorkItemMatch,
)


def test_valid_catalog_rule():
    rule = DocumentationCatalogRule(
        area="Review orchestration",
        patterns=["baloo/review/**"],
        recommended_docs=["docs/features/review-agent.md"],
    )

    catalog = DocumentationCatalog(rules=[rule])

    assert catalog.schema_version == 1
    assert catalog.rules[0].area == "Review orchestration"
    assert catalog.rules[0].read_only is False


def test_default_empty_analysis_result():
    result = DocumentationDriftResult()

    assert result.summary == ""
    assert result.required_updates == []
    assert result.optional_updates == []
    assert result.not_needed == []
    assert result.catalog_gaps == []
    assert result.metadata == {}


def test_drift_finding_fields():
    finding = DocumentationDriftFinding(
        doc_path="docs/features/review-agent.md",
        verdict="required",
        rationale="The review lifecycle changed.",
        evidence=["baloo/review/orchestrator.py"],
        suggested_update="Mention documentation drift analysis.",
    )

    assert finding.doc_path == "docs/features/review-agent.md"
    assert finding.verdict == "required"
    assert finding.rationale == "The review lifecycle changed."
    assert finding.evidence == ["baloo/review/orchestrator.py"]
    assert finding.suggested_update == "Mention documentation drift analysis."


def test_invalid_verdict_rejected():
    with pytest.raises(ValidationError):
        DocumentationDriftFinding(
            doc_path="README.md",
            verdict="must_update",
            rationale="Invalid verdict.",
        )


def test_work_item_state_fields():
    match = DocumentationWorkItemMatch(
        area="Review orchestration",
        matched_files=["baloo/review/orchestrator.py"],
        docs_already_changed=["docs/features/review-agent.md"],
        docs_to_review=["README.md"],
    )
    item = DocumentationWorkItem(
        repo_full_name="org/repo",
        pr_number=12,
        title="Add docs drift",
        changed_files=[
            "baloo/review/orchestrator.py",
            "docs/features/review-agent.md",
            "baloo/documentation/analyzer.py",
        ],
        matches=[match],
        unmapped_files=["baloo/documentation/analyzer.py"],
        has_relevant_impl_changes=True,
        has_docs_to_review=True,
        has_docs_already_changed=True,
        has_catalog_gaps=True,
        needs_analysis=True,
    )

    assert item.matches == [match]
    assert item.has_relevant_impl_changes is True
    assert item.has_docs_to_review is True
    assert item.has_docs_already_changed is True
    assert item.has_catalog_gaps is True
    assert item.needs_analysis is True
