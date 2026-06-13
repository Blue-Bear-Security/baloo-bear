"""Tests for documentation drift work item construction."""

from baloo.documentation.models import DocumentationCatalog, DocumentationCatalogRule
from baloo.documentation.work_items import (
    build_documentation_work_item,
    is_documentation_path,
    rule_matches_path,
)
from baloo.github.models import (
    FileChange,
    PRContext,
    PRDiscussionContext,
    PRMetadata,
)


def _pr_context(files: list[str]) -> PRContext:
    return PRContext(
        metadata=PRMetadata(
            repo_full_name="org/repo",
            pr_number=7,
            title="Change review behavior",
            description="",
            author="dev",
            base_branch="main",
            head_branch="feat/docs-drift",
            head_sha="abc123",
            files_changed=[
                FileChange(filename=f, status="modified", additions=1, deletions=0, changes=1)
                for f in files
            ],
            commit_messages=[],
        ),
        discussion=PRDiscussionContext(),
        diff="+ change",
    )


def _catalog() -> DocumentationCatalog:
    return DocumentationCatalog(
        rules=[
            DocumentationCatalogRule(
                area="Review orchestration",
                patterns=["baloo/review/**"],
                recommended_docs=["docs/features/review-agent.md", "README.md"],
            ),
            DocumentationCatalogRule(
                area="Runtime context",
                patterns=["baloo/agent/*"],
                recommended_docs=["docs/features/models.md"],
            ),
            DocumentationCatalogRule(
                area="Read-only internals",
                patterns=["baloo/internal/**"],
                recommended_docs=["docs/internal.md"],
                read_only=True,
            ),
        ]
    )


def test_is_documentation_path():
    assert is_documentation_path("README.md")
    assert is_documentation_path("docs/guide.mdx")
    assert is_documentation_path("docs/api.rst")
    assert is_documentation_path("docs/data.csv")
    assert not is_documentation_path("baloo/review/orchestrator.py")


def test_docs_already_changed_are_excluded_from_docs_to_review():
    item = build_documentation_work_item(
        pr_context=_pr_context(["baloo/review/orchestrator.py", "docs/features/review-agent.md"]),
        catalog=_catalog(),
    )

    match = item.matches[0]
    assert match.docs_already_changed == ["docs/features/review-agent.md"]
    assert match.docs_to_review == ["README.md"]
    assert item.has_docs_already_changed is True
    assert item.needs_analysis is True


def test_docs_already_changed_still_need_sufficiency_analysis():
    catalog = DocumentationCatalog(
        rules=[
            DocumentationCatalogRule(
                area="Review orchestration",
                patterns=["baloo/review/**"],
                recommended_docs=["docs/features/review-agent.md"],
            )
        ]
    )

    item = build_documentation_work_item(
        pr_context=_pr_context(["baloo/review/orchestrator.py", "docs/features/review-agent.md"]),
        catalog=catalog,
    )

    assert item.has_docs_to_review is False
    assert item.has_docs_already_changed is True
    assert item.needs_analysis is True


def test_unmapped_implementation_files_are_surfaced():
    item = build_documentation_work_item(
        pr_context=_pr_context(["baloo/documentation/analyzer.py"]),
        catalog=_catalog(),
    )

    assert item.unmapped_files == ["baloo/documentation/analyzer.py"]
    assert item.has_catalog_gaps is True
    assert item.needs_analysis is True


def test_read_only_rules_do_not_create_docs_to_review():
    item = build_documentation_work_item(
        pr_context=_pr_context(["baloo/internal/cache.py"]),
        catalog=_catalog(),
    )

    assert item.matches[0].area == "Read-only internals"
    assert item.matches[0].docs_to_review == []
    assert item.unmapped_files == []


def test_doc_only_pr_without_mapped_impl_changes_skips_analysis():
    item = build_documentation_work_item(
        pr_context=_pr_context(["docs/features/review-agent.md"]),
        catalog=_catalog(),
    )

    assert item.has_relevant_impl_changes is False
    assert item.needs_analysis is False


def test_path_matching_star_and_globstar():
    assert rule_matches_path("baloo/agent/client.py", ["baloo/agent/*"])
    assert not rule_matches_path("baloo/agent/nested/client.py", ["baloo/agent/*"])
    assert rule_matches_path("baloo/agent/nested/client.py", ["baloo/agent/**"])
    assert rule_matches_path("baloo/review/orchestrator.py", ["baloo/**/*.py"])
    assert rule_matches_path("db/migrations/001_create_users.py", ["**/migrations/**"])
    assert rule_matches_path("migrations/001_create_users.py", ["**/migrations/**"])
    assert rule_matches_path("app.py", ["**/*.py"])
    assert rule_matches_path("baloo/review/orchestrator.py", ["**/*.py"])
    assert rule_matches_path("baloo/review/orchestrator.py", ["**"])
