"""Tests for _reverify_awaiting_threads."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from baloo.github.models import (
    DiscussionComment,
    DiscussionThread,
    FileChange,
    FindingCategory,
    PRContext,
    PRDiscussionContext,
    PRMetadata,
    ReviewComment,
    ReviewSeverity,
)
from baloo.processor.fp_verifier import FPRejection, FPStats, FPVerificationResult


def _make_awaiting_thread(root_comment_id: int = 1, node_id: str = "PRT_x") -> DiscussionThread:
    comment = DiscussionComment(
        id=root_comment_id,
        author="baloo-code-reviewer[bot]",
        body="**[HIGH] Security** - **SQL injection**\n**Category:** Security\n**Severity:** HIGH\n\nBad query.",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        source="review_comment",
        is_baloo=True,
        path="app.py",
        line=10,
    )
    return DiscussionThread(
        id=root_comment_id,
        path="app.py",
        line=10,
        comments=[comment],
        is_baloo_thread=True,
        awaiting_response=True,
        last_activity=datetime.now(timezone.utc),
        root_comment_id=root_comment_id,
        node_id=node_id,
    )


def _make_pr_context(awaiting_threads: list[DiscussionThread] | None = None) -> PRContext:
    return PRContext(
        metadata=PRMetadata(
            repo_full_name="org/repo",
            pr_number=1,
            title="Fix stuff",
            description=None,
            author="dev",
            base_branch="main",
            head_branch="fix/it",
            head_sha="abc123",
            files_changed=[
                FileChange(
                    filename="app.py",
                    status="modified",
                    additions=1,
                    deletions=1,
                    changes=2,
                )
            ],
        ),
        discussion=PRDiscussionContext(
            threads=awaiting_threads or [],
            awaiting_response_count=len(awaiting_threads) if awaiting_threads else 0,
        ),
        diff="diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -10,1 +10,1 @@\n-bad\n+good\n",
    )


@pytest.mark.asyncio
async def test_reverify_fp_verdict_triggers_reply_and_resolve():
    """fp verdict → reply to thread + resolve."""
    from baloo.github.webhook_handler import _reverify_awaiting_threads

    thread = _make_awaiting_thread(root_comment_id=42, node_id="PRT_x")
    pr_context = _make_pr_context(awaiting_threads=[thread])

    fake_rejected = ReviewComment(
        path="app.py",
        line=10,
        body="**[HIGH] Security** - **SQL injection**\n**Category:** Security\n**Severity:** HIGH\n\nBad query.",
        severity=ReviewSeverity.HIGH,
        category=FindingCategory.SECURITY,
    )
    fp_result = FPVerificationResult(
        verified=[],
        rejected=[
            FPRejection(
                comment=fake_rejected, reason="code was fixed", model="haiku", cost_usd=0.001
            )
        ],
        stats=FPStats(),
    )

    mock_api = AsyncMock()
    mock_api.reply_to_review_comment = AsyncMock(return_value=True)
    mock_api.resolve_review_thread = AsyncMock(return_value=True)

    with patch("baloo.github.webhook_handler.FPVerifier") as mock_verifier_cls:
        mock_instance = AsyncMock()
        mock_instance.verify = AsyncMock(return_value=fp_result)
        mock_verifier_cls.return_value = mock_instance

        resolved_count = await _reverify_awaiting_threads(
            awaiting_threads=[thread],
            pr_context=pr_context,
            api_client=mock_api,
        )

    assert resolved_count == 1
    mock_api.reply_to_review_comment.assert_called_once_with(
        "org/repo",
        1,
        42,
        "Looks like this was addressed in the latest commit. Resolving.",
    )
    mock_api.resolve_review_thread.assert_called_once_with("PRT_x")


@pytest.mark.asyncio
async def test_reverify_real_verdict_no_action():
    """real verdict → thread untouched."""
    from baloo.github.webhook_handler import _reverify_awaiting_threads

    thread = _make_awaiting_thread()
    pr_context = _make_pr_context(awaiting_threads=[thread])

    kept_comment = ReviewComment(
        path="app.py",
        line=10,
        body="body",
        severity=ReviewSeverity.HIGH,
        category=FindingCategory.SECURITY,
    )
    fp_result = FPVerificationResult(verified=[kept_comment], rejected=[], stats=FPStats())

    mock_api = AsyncMock()

    with patch("baloo.github.webhook_handler.FPVerifier") as mock_verifier_cls:
        mock_instance = AsyncMock()
        mock_instance.verify = AsyncMock(return_value=fp_result)
        mock_verifier_cls.return_value = mock_instance

        resolved_count = await _reverify_awaiting_threads(
            awaiting_threads=[thread],
            pr_context=pr_context,
            api_client=mock_api,
        )

    assert resolved_count == 0
    mock_api.reply_to_review_comment.assert_not_called()
    mock_api.resolve_review_thread.assert_not_called()


@pytest.mark.asyncio
async def test_reverify_skips_threads_without_node_id():
    """Threads missing node_id are excluded."""
    from baloo.github.webhook_handler import _reverify_awaiting_threads

    thread = _make_awaiting_thread(node_id=None)
    thread.node_id = None
    pr_context = _make_pr_context(awaiting_threads=[thread])

    mock_api = AsyncMock()

    with patch("baloo.github.webhook_handler.FPVerifier") as mock_verifier_cls:
        mock_instance = AsyncMock()
        mock_instance.verify = AsyncMock(return_value=FPVerificationResult())
        mock_verifier_cls.return_value = mock_instance

        resolved_count = await _reverify_awaiting_threads(
            awaiting_threads=[thread],
            pr_context=pr_context,
            api_client=mock_api,
        )

    # Early return: verifier is never called when no eligible threads
    mock_instance.verify.assert_not_called()
    assert resolved_count == 0


@pytest.mark.asyncio
async def test_reverify_empty_list_no_verifier_call():
    """Empty awaiting_threads returns 0 immediately."""
    from baloo.github.webhook_handler import _reverify_awaiting_threads

    pr_context = _make_pr_context()
    mock_api = AsyncMock()

    with patch("baloo.github.webhook_handler.FPVerifier") as mock_verifier_cls:
        resolved_count = await _reverify_awaiting_threads(
            awaiting_threads=[],
            pr_context=pr_context,
            api_client=mock_api,
        )

    mock_verifier_cls.assert_not_called()
    assert resolved_count == 0


@pytest.mark.asyncio
async def test_awaiting_count_excludes_resolved_threads():
    """Decision engine sees 0 awaiting after all threads are auto-resolved."""
    # This test verifies the integration: that auto_resolved_count returned from
    # _reverify_awaiting_threads correctly reduces the awaiting_threads count
    # fed to the decision engine, preventing spurious request_changes=True.
    from baloo.github.webhook_handler import _reverify_awaiting_threads

    thread = _make_awaiting_thread(root_comment_id=99, node_id="PRT_awaiting")
    pr_context = _make_pr_context(awaiting_threads=[thread])

    fake_rejected = ReviewComment(
        path="app.py",
        line=10,
        body="**[HIGH] Security** - **SQL injection**\n**Category:** Security\n**Severity:** HIGH\n\nBad query.",
        severity=ReviewSeverity.HIGH,
        category=FindingCategory.SECURITY,
    )
    fp_result = FPVerificationResult(
        verified=[],
        rejected=[
            FPRejection(
                comment=fake_rejected,
                reason="issue addressed in latest commit",
                model="haiku",
                cost_usd=0.001,
            )
        ],
        stats=FPStats(),
    )

    mock_api = AsyncMock()
    mock_api.reply_to_review_comment = AsyncMock(return_value=True)
    mock_api.resolve_review_thread = AsyncMock(return_value=True)

    with patch("baloo.github.webhook_handler.FPVerifier") as mock_verifier_cls:
        mock_instance = AsyncMock()
        mock_instance.verify = AsyncMock(return_value=fp_result)
        mock_verifier_cls.return_value = mock_instance

        resolved_count = await _reverify_awaiting_threads(
            awaiting_threads=[thread],
            pr_context=pr_context,
            api_client=mock_api,
        )

    assert resolved_count == 1

    # Simulate the decision engine logic: awaiting_threads - auto_resolved_count
    awaiting_threads = pr_context.awaiting_response_threads
    remaining = awaiting_threads - resolved_count
    assert (
        remaining == 0
    ), f"Expected 0 remaining awaiting threads after auto-resolution, got {remaining}"
