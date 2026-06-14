"""Tests for documentation drift prompts."""

from baloo.documentation.models import (
    DocumentationWorkItem,
    DocumentationWorkItemMatch,
)
from baloo.documentation.prompts import build_documentation_drift_prompt
from baloo.github.models import (
    FileChange,
    PRContext,
    PRDiscussionContext,
    PRMetadata,
)


def _pr_context() -> PRContext:
    return PRContext(
        metadata=PRMetadata(
            repo_full_name="org/repo",
            pr_number=7,
            title="Add documentation drift review",
            description="Adds side analysis",
            author="dev",
            base_branch="main",
            head_branch="feat/docs-drift",
            head_sha="abc123",
            files_changed=[
                FileChange(
                    filename="baloo/review/orchestrator.py",
                    status="modified",
                    additions=10,
                    deletions=1,
                    changes=11,
                )
            ],
            commit_messages=[],
        ),
        discussion=PRDiscussionContext(),
        diff="diff --git a/baloo/review/orchestrator.py b/baloo/review/orchestrator.py\n+docs",
    )


def _work_item() -> DocumentationWorkItem:
    return DocumentationWorkItem(
        repo_full_name="org/repo",
        pr_number=7,
        title="Add documentation drift review",
        changed_files=["baloo/review/orchestrator.py", "docs/features/review-agent.md"],
        matches=[
            DocumentationWorkItemMatch(
                area="Review orchestration",
                matched_files=["baloo/review/orchestrator.py"],
                docs_already_changed=["docs/features/review-agent.md"],
                docs_to_review=["README.md"],
            )
        ],
        unmapped_files=["baloo/documentation/analyzer.py"],
        has_relevant_impl_changes=True,
        has_docs_to_review=True,
        has_docs_already_changed=True,
        has_catalog_gaps=True,
        needs_analysis=True,
    )


def test_prompt_includes_changed_files_and_matched_docs():
    prompt = build_documentation_drift_prompt(
        pr_context=_pr_context(),
        work_item=_work_item(),
        catalog_path=".baloo/documentation-catalog.json",
    )

    assert "baloo/review/orchestrator.py" in prompt
    assert "README.md" in prompt
    assert "docs_to_review" in prompt
    assert "ignored_unmapped_files" in prompt


def test_prompt_includes_docs_already_changed():
    prompt = build_documentation_drift_prompt(
        pr_context=_pr_context(),
        work_item=_work_item(),
        catalog_path=".baloo/documentation-catalog.json",
    )

    assert "docs_already_changed" in prompt
    assert "docs/features/review-agent.md" in prompt
    assert "decide whether they are sufficient" in prompt


def test_prompt_requires_author_focused_action_summary():
    prompt = build_documentation_drift_prompt(
        pr_context=_pr_context(),
        work_item=_work_item(),
        catalog_path=".baloo/documentation-catalog.json",
    )

    assert "Use these action_required values" in prompt
    assert 'Do not include an "Already Covered" section' in prompt
    assert "Treat unmapped_files as catalog hygiene" in prompt
    assert "Action required: none" in prompt
    assert "Action required: update docs" in prompt


def test_prompt_forbids_file_edits():
    prompt = build_documentation_drift_prompt(
        pr_context=_pr_context(),
        work_item=_work_item(),
        catalog_path=".baloo/documentation-catalog.json",
    )

    assert "Do not edit files" in prompt
    assert "Do not create branches" in prompt
