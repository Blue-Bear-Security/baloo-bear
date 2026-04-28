"""Tests for the local Baloo review CLI."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from baloo.github.models import ReviewComment, ReviewResult
from scripts.local_review import _parse_numstat, build_local_pr_context, run_local_review


def test_parse_numstat_skips_malformed_lines():
    """Malformed git numstat lines should not crash parsing."""
    stats = _parse_numstat("1\t2\n7\t8\tgood.py\n")
    assert stats == {"good.py": (7, 8)}


def test_build_local_pr_context_from_git_diff():
    """Synthetic PR context should be built from local git state."""
    outputs = {
        ("rev-parse", "--show-toplevel"): "/repo",
        ("rev-parse", "--abbrev-ref", "HEAD"): "fix/local-review",
        ("rev-parse", "HEAD"): "abc123",
        (
            "config",
            "--get",
            "remote.origin.url",
        ): "git@github.com:Blue-Bear-Security/baloo-bear.git",
        ("diff", "--numstat", "origin/main...HEAD"): "3\t1\tbaloo/foo.py\n-\t-\tbinary.bin\n",
        ("diff", "--name-status", "origin/main...HEAD"): "M\tbaloo/foo.py\nA\tbinary.bin\n",
        (
            "diff",
            "origin/main...HEAD",
        ): "diff --git a/baloo/foo.py b/baloo/foo.py\n@@ -1 +1 @@\n-old\n+new\n",
        ("show", "HEAD:AGENTS.md"): "Repo guidelines",
        ("show", "HEAD:CONTRIBUTING.md"): "",
    }

    def fake_git(args, cwd=None, check=True):
        return outputs[tuple(args)]

    context = build_local_pr_context(
        base="origin/main",
        head="HEAD",
        title="Local review",
        description="Dry run",
        author="dev",
        git=fake_git,
    )

    assert context.pr_number == 0
    assert context.repo_full_name == "Blue-Bear-Security/baloo-bear"
    assert context.base_branch == "origin/main"
    assert context.head_branch == "fix/local-review"
    assert context.head_sha == "abc123"
    assert context.repo_guidelines == "Repo guidelines"
    assert context.diff.startswith("diff --git")
    assert [f.filename for f in context.files_changed] == ["baloo/foo.py", "binary.bin"]
    assert context.files_changed[0].status == "modified"
    assert context.files_changed[0].additions == 3
    assert context.files_changed[1].additions == 0


@pytest.mark.asyncio
async def test_run_local_review_prints_summary_and_returns_blocking_status(capsys):
    """CLI runner should call BalooAgent without posting to GitHub."""
    context = MagicMock()
    result = ReviewResult(
        summary="## Summary",
        comments=[
            ReviewComment(
                path="file.py",
                line=10,
                body="High issue",
                severity="HIGH",
                category="Bugs",
            )
        ],
        approve=False,
        request_changes=True,
    )
    agent = MagicMock()
    agent.review_pr = AsyncMock(return_value=result)

    exit_code = await run_local_review(
        context=context,
        agent=agent,
        model=None,
        output_json=False,
        fail_on_blocking=True,
    )

    captured = capsys.readouterr()
    assert "## Summary" in captured.out
    assert "[HIGH] Bugs - file.py:10" in captured.out
    assert exit_code == 1
    agent.review_pr.assert_awaited_once_with(context)
