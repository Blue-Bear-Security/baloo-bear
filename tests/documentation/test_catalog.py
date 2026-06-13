"""Tests for documentation catalog loading."""

import json

from baloo.documentation.catalog import load_documentation_catalog


def test_returns_none_when_repo_path_missing():
    assert load_documentation_catalog(None, ".baloo/documentation-catalog.json") is None


def test_returns_none_when_catalog_missing(tmp_path):
    assert load_documentation_catalog(str(tmp_path), ".baloo/documentation-catalog.json") is None


def test_parses_valid_json(tmp_path):
    catalog_path = tmp_path / ".baloo" / "documentation-catalog.json"
    catalog_path.parent.mkdir()
    catalog_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "rules": [
                    {
                        "area": "Review orchestration",
                        "patterns": ["baloo/review/**"],
                        "recommended_docs": ["docs/features/review-agent.md"],
                    }
                ],
            }
        )
    )

    catalog = load_documentation_catalog(str(tmp_path), ".baloo/documentation-catalog.json")

    assert catalog is not None
    assert catalog.rules[0].area == "Review orchestration"


def test_returns_none_and_logs_warning_for_invalid_json(tmp_path, caplog):
    catalog_path = tmp_path / ".baloo" / "documentation-catalog.json"
    catalog_path.parent.mkdir()
    catalog_path.write_text("{not json")

    catalog = load_documentation_catalog(str(tmp_path), ".baloo/documentation-catalog.json")

    assert catalog is None
    assert "Invalid documentation catalog" in caplog.text


def test_rejects_absolute_catalog_path(tmp_path):
    absolute = tmp_path / "catalog.json"
    absolute.write_text("{}")

    assert load_documentation_catalog(str(tmp_path), str(absolute)) is None


def test_rejects_parent_traversal(tmp_path):
    outside = tmp_path.parent / "catalog.json"
    outside.write_text("{}")

    assert load_documentation_catalog(str(tmp_path), "../catalog.json") is None


def test_rejects_normalized_traversal(tmp_path):
    nested = tmp_path / ".baloo"
    nested.mkdir()
    outside = tmp_path.parent / "catalog.json"
    outside.write_text("{}")

    assert load_documentation_catalog(str(tmp_path), ".baloo/../../catalog.json") is None
