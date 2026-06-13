"""Tests for the documentation drift PI analyzer."""

from unittest.mock import AsyncMock, patch

import pytest

from baloo.documentation.analyzer import DocumentationDriftAgent, analyze_documentation_drift
from baloo.documentation.models import (
    DocumentationDriftFinding,
    DocumentationWorkItem,
)
from baloo.documentation.prompts import DOCUMENTATION_DRIFT_SYSTEM_PROMPT
from baloo.github.models import FileChange, PRContext, PRDiscussionContext, PRMetadata


def _pr_context() -> PRContext:
    return PRContext(
        metadata=PRMetadata(
            repo_full_name="org/repo",
            pr_number=7,
            title="Add docs drift",
            description="",
            author="dev",
            base_branch="main",
            head_branch="feat/docs-drift",
            head_sha="abc123",
            files_changed=[
                FileChange(
                    filename="baloo/review/orchestrator.py",
                    status="modified",
                    additions=1,
                    deletions=0,
                    changes=1,
                )
            ],
            commit_messages=[],
        ),
        discussion=PRDiscussionContext(),
        diff="+ change",
    )


def _work_item() -> DocumentationWorkItem:
    return DocumentationWorkItem(
        repo_full_name="org/repo",
        pr_number=7,
        title="Add docs drift",
        changed_files=["baloo/review/orchestrator.py"],
        matches=[],
        unmapped_files=["baloo/review/orchestrator.py"],
        has_relevant_impl_changes=False,
        has_docs_to_review=False,
        has_docs_already_changed=False,
        has_catalog_gaps=True,
        needs_analysis=True,
    )


@pytest.mark.asyncio
async def test_analyzer_sets_cwd_model_and_system_prompt():
    with patch(
        "baloo.documentation.analyzer.DocumentationDriftAgent.run_query",
        new=AsyncMock(return_value=({"summary": "ok"}, {})),
    ):
        agent = DocumentationDriftAgent(model="haiku")
        result = await agent.analyze(
            pr_context=_pr_context(),
            work_item=_work_item(),
            catalog_path=".baloo/documentation-catalog.json",
            repo_path="/tmp/repo",
        )

    assert result is not None
    assert agent.options.cwd == "/tmp/repo"
    assert agent.options.model == "claude-haiku-4-5-20251001"
    assert agent.options.system_prompt == DOCUMENTATION_DRIFT_SYSTEM_PROMPT
    assert agent.options.name == "DocumentationDriftAgent"


@pytest.mark.asyncio
async def test_valid_structured_output_parses_and_attaches_metadata():
    metadata = {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.01}
    output = {
        "summary": "Docs need updates.",
        "required_updates": [
            {
                "doc_path": "README.md",
                "verdict": "required",
                "rationale": "Feature behavior changed.",
                "evidence": ["baloo/review/orchestrator.py"],
                "suggested_update": "Mention documentation drift.",
            }
        ],
        "catalog_gaps": ["baloo/documentation/analyzer.py"],
    }

    with patch(
        "baloo.documentation.analyzer.DocumentationDriftAgent.run_query",
        new=AsyncMock(return_value=(output, metadata)),
    ):
        result = await analyze_documentation_drift(
            pr_context=_pr_context(),
            work_item=_work_item(),
            catalog_path=".baloo/documentation-catalog.json",
            repo_path="/tmp/repo",
            model="sonnet",
        )

    assert result is not None
    assert result.summary == "Docs need updates."
    assert result.required_updates[0] == DocumentationDriftFinding(
        doc_path="README.md",
        verdict="required",
        rationale="Feature behavior changed.",
        evidence=["baloo/review/orchestrator.py"],
        suggested_update="Mention documentation drift.",
    )
    assert result.metadata == metadata


@pytest.mark.asyncio
async def test_invalid_or_missing_structured_output_returns_none():
    with patch(
        "baloo.documentation.analyzer.DocumentationDriftAgent.run_query",
        new=AsyncMock(return_value=(None, {})),
    ):
        missing = await analyze_documentation_drift(
            pr_context=_pr_context(),
            work_item=_work_item(),
            catalog_path=".baloo/documentation-catalog.json",
            repo_path="/tmp/repo",
            model="sonnet",
        )

    with patch(
        "baloo.documentation.analyzer.DocumentationDriftAgent.run_query",
        new=AsyncMock(return_value=({"required_updates": [{"verdict": "bad"}]}, {})),
    ):
        invalid = await analyze_documentation_drift(
            pr_context=_pr_context(),
            work_item=_work_item(),
            catalog_path=".baloo/documentation-catalog.json",
            repo_path="/tmp/repo",
            model="sonnet",
        )

    assert missing is None
    assert invalid is None


@pytest.mark.asyncio
async def test_review_logger_is_passed_to_run_query():
    review_logger = object()
    run_query = AsyncMock(return_value=({"summary": "ok"}, {}))

    with patch("baloo.documentation.analyzer.DocumentationDriftAgent.run_query", new=run_query):
        await analyze_documentation_drift(
            pr_context=_pr_context(),
            work_item=_work_item(),
            catalog_path=".baloo/documentation-catalog.json",
            repo_path="/tmp/repo",
            model="sonnet",
            review_logger=review_logger,
        )

    assert run_query.call_args.kwargs["review_logger"] is review_logger
