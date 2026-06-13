"""Regression tests for Baloo's own documentation drift catalog."""

from pathlib import Path

from baloo.documentation.catalog import load_documentation_catalog
from baloo.documentation.work_items import rule_matches_path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_baloo_catalog_loads():
    catalog = load_documentation_catalog(
        str(REPO_ROOT),
        ".baloo/documentation-catalog.json",
    )

    assert catalog is not None
    assert catalog.schema_version == 1
    assert catalog.rules


def test_baloo_catalog_recommended_docs_exist():
    catalog = load_documentation_catalog(
        str(REPO_ROOT),
        ".baloo/documentation-catalog.json",
    )
    assert catalog is not None

    docs = {doc_path for rule in catalog.rules for doc_path in rule.recommended_docs}

    missing = sorted(doc_path for doc_path in docs if not (REPO_ROOT / doc_path).exists())
    assert missing == []


def test_baloo_catalog_covers_documentation_drift_package():
    catalog = load_documentation_catalog(
        str(REPO_ROOT),
        ".baloo/documentation-catalog.json",
    )
    assert catalog is not None

    matching_rules = [
        rule
        for rule in catalog.rules
        if rule_matches_path("baloo/documentation/analyzer.py", rule.patterns)
    ]

    assert [rule.area for rule in matching_rules] == ["Documentation drift"]
    assert "docs/features/documentation-drift.md" in matching_rules[0].recommended_docs
