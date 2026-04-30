"""Tests for webhook handler completion messages."""

from contextlib import ExitStack
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from baloo.fidelity.fidelity_report import (
    ERROR_FIDELITY_SENTINEL,
    MISSING_PLAN_FIDELITY_SENTINEL,
    NO_TICKET_FIDELITY_SENTINEL,
)
from baloo.fidelity.models import FidelityResult
from baloo.github.api_client import DroppedReviewComment, PostedReviewResult
from baloo.github.models import DiscussionComment, DiscussionThread, ReviewComment, ReviewResult
from baloo.github.webhook_handler import _total_review_cost_usd, process_pr_review


def _baloo_thread(
    *,
    thread_id: int,
    path: str,
    line: int,
    body: str,
    awaiting_response: bool = False,
    resolved: bool = False,
) -> DiscussionThread:
    now = datetime.now(timezone.utc)
    return DiscussionThread(
        id=thread_id,
        path=path,
        line=line,
        comments=[
            DiscussionComment(
                id=thread_id,
                author="baloo-code-reviewer[bot]",
                body=body,
                created_at=now,
                updated_at=now,
                source="review_comment",
                is_baloo=True,
                path=path,
                line=line,
            )
        ],
        is_baloo_thread=True,
        awaiting_response=awaiting_response,
        resolved=resolved,
        last_activity=now,
        root_comment_id=thread_id,
    )


def test_total_review_cost_includes_fp_verification_cost():
    """Persisted review cost should include main, fidelity, and FP verifier calls."""
    total = _total_review_cost_usd(
        {
            "cost_usd": 0.10,
            "fp_verification": {"cost_usd": 0.03},
        },
        {"cost_usd": 0.02},
    )

    assert total == pytest.approx(0.15)


@pytest.mark.asyncio
async def test_review_summary_uses_actionable_findings_after_resolved_thread_skip():
    """Review body counts should reflect deduped actionable findings, not raw agent output."""
    mock_github_client = MagicMock()
    mock_github_client.post_comment = AsyncMock()
    mock_github_client.edit_comment = AsyncMock()
    mock_github_client.reply_to_review_comment = AsyncMock()
    mock_github_client.post_review = AsyncMock(
        return_value=PostedReviewResult(attempted=1, posted=1, dropped=[])
    )

    resolved_body = "**[HIGH] Bugs** - Existing resolved issue"
    mock_pr_context = MagicMock()
    mock_pr_context.discussion_threads = [
        _baloo_thread(
            thread_id=111,
            path="file.py",
            line=10,
            body=resolved_body,
            awaiting_response=False,
            resolved=True,
        )
    ]
    mock_pr_context.issue_comments = []
    mock_pr_context.awaiting_response_threads = 0
    mock_pr_context.head_sha = "abc123"
    mock_pr_context.head_branch = "fix/counts"
    mock_pr_context.title = "Fix counts"
    mock_pr_context.description = ""
    mock_pr_context.diff = "+ added code"
    mock_github_client.get_pr_context = AsyncMock(return_value=mock_pr_context)

    mock_agent = MagicMock()
    mock_agent.review_pr = AsyncMock(
        return_value=ReviewResult(
            summary="## 🐻 Baloo Review Summary\n\n🟠 **2** High\n**Total**: 2 issue(s) found",
            comments=[
                ReviewComment(
                    path="file.py",
                    line=10,
                    body="**Existing resolved issue**\n\nStill present",
                    severity="HIGH",
                    category="Bugs",
                ),
                ReviewComment(
                    path="new.py",
                    line=20,
                    body="**Fresh issue**\n\nNew actionable finding",
                    severity="HIGH",
                    category="Bugs",
                ),
            ],
            approve=False,
            request_changes=True,
        )
    )

    with (
        patch("baloo.github.webhook_handler.GitHubAPIClient", return_value=mock_github_client),
        patch("baloo.agent.client.BalooAgent", return_value=mock_agent),
        patch("baloo.config.settings.settings.fidelity_enabled", False),
        patch("baloo.config.settings.settings.fp_verification_enabled", False),
        patch("baloo.github.webhook_handler.settings.fp_verification_enabled", False),
        patch("baloo.config.settings.settings.review_min_severity", "MEDIUM"),
    ):
        await process_pr_review(
            repo_full_name="test/repo",
            pr_number=123,
            installation_id=456,
            trigger_reason="test",
            notify_progress=False,
        )

    posted_review = mock_github_client.post_review.call_args.args[2]
    assert "**Total**: 1 issue(s) found" in posted_review.summary
    assert "**Total**: 2 issue(s) found" not in posted_review.summary
    assert "✅ Skipped 1 resolved thread(s)." in posted_review.summary


@pytest.mark.asyncio
async def test_progress_comment_reports_dropped_inline_findings_internally():
    """Progress comments should not imply every actionable finding was posted inline."""
    mock_github_client = MagicMock()
    mock_github_client.post_comment = AsyncMock(return_value=12345)
    mock_github_client.edit_comment = AsyncMock()
    mock_github_client.reply_to_review_comment = AsyncMock()

    dropped_comment = ReviewComment(
        path="file.py",
        line=99,
        body="Dropped high finding with enough detail",
        severity="HIGH",
        category="Bugs",
    )
    mock_github_client.post_review = AsyncMock(
        return_value=PostedReviewResult(
            attempted=2,
            posted=1,
            dropped=[
                DroppedReviewComment(
                    comment=dropped_comment,
                    reason="line_not_in_diff",
                    nearest_valid_line=10,
                )
            ],
        )
    )

    mock_pr_context = MagicMock()
    mock_pr_context.discussion_threads = []
    mock_pr_context.issue_comments = []
    mock_pr_context.awaiting_response_threads = 0
    mock_pr_context.head_sha = "abc123"
    mock_pr_context.head_branch = "fix/counts"
    mock_pr_context.title = "Fix counts"
    mock_pr_context.description = ""
    mock_pr_context.diff = "+ added code"
    mock_github_client.get_pr_context = AsyncMock(return_value=mock_pr_context)

    mock_agent = MagicMock()
    mock_agent.review_pr = AsyncMock(
        return_value=ReviewResult(
            summary="Raw summary",
            comments=[
                ReviewComment(
                    path="file.py",
                    line=10,
                    body="Posted high finding with enough detail",
                    severity="HIGH",
                    category="Bugs",
                ),
                dropped_comment,
            ],
            approve=False,
            request_changes=True,
        )
    )

    with (
        patch("baloo.github.webhook_handler.GitHubAPIClient", return_value=mock_github_client),
        patch("baloo.agent.client.BalooAgent", return_value=mock_agent),
        patch("baloo.config.settings.settings.fidelity_enabled", False),
        patch("baloo.config.settings.settings.fp_verification_enabled", False),
        patch("baloo.github.webhook_handler.settings.fp_verification_enabled", False),
        patch("baloo.config.settings.settings.review_min_severity", "MEDIUM"),
    ):
        await process_pr_review(
            repo_full_name="test/repo",
            pr_number=123,
            installation_id=456,
            trigger_reason="test",
            notify_progress=True,
        )

    completion_msg = mock_github_client.edit_comment.call_args.args[2]
    assert "Found 2 issue(s)" in completion_msg
    assert "Posted 1 inline comment(s)." in completion_msg
    assert "Dropped 1 inline finding(s)" in completion_msg


@pytest.mark.asyncio
async def test_does_not_repost_missing_plan_fidelity_report():
    """Do not post the missing-plan fidelity report more than once per PR."""

    mock_github_client = MagicMock()
    mock_github_client.post_comment = AsyncMock(return_value=12345)
    mock_github_client.edit_comment = AsyncMock()
    mock_github_client.post_review = AsyncMock()
    mock_github_client.reply_to_review_comment = AsyncMock()

    mock_pr_context = MagicMock()
    mock_pr_context.discussion_threads = []
    mock_pr_context.issue_comments = [
        DiscussionComment(
            id=111,
            author="baloo[bot]",
            body=(
                "<details>\n"
                "<summary>📋 Fidelity Report (DEN-123) - ⏭️ Skipped</summary>\n\n"
                "**No plan file found at `docs/plans/DEN-123.md`**\n\n"
                "</details>"
            ),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source="issue_comment",
            is_baloo=True,
        )
    ]
    mock_pr_context.awaiting_response_threads = 0
    mock_pr_context.head_sha = "abc123"
    mock_pr_context.head_branch = "feat/DEN-123/add-feature"
    mock_pr_context.title = "Add new feature"
    mock_pr_context.description = "This PR adds a new feature"
    mock_pr_context.diff = "+ added code"
    mock_github_client.get_pr_context = AsyncMock(return_value=mock_pr_context)

    mock_agent = MagicMock()
    mock_agent.review_pr = AsyncMock(
        return_value=ReviewResult(
            summary="Review complete",
            comments=[],
            approve=True,
            request_changes=False,
        )
    )

    with (
        patch("baloo.github.webhook_handler.GitHubAPIClient", return_value=mock_github_client),
        patch("baloo.agent.client.BalooAgent", return_value=mock_agent),
        patch("baloo.config.settings.settings.fidelity_enabled", True),
        patch("baloo.config.settings.settings.review_auto_approve", True),
        patch("baloo.github.webhook_handler.extract_ticket_id", return_value="DEN-123"),
        patch(
            "baloo.github.webhook_handler.fetch_plan_content",
            AsyncMock(return_value=None),
        ),
    ):
        await process_pr_review(
            repo_full_name="test/repo",
            pr_number=123,
            installation_id=456,
            trigger_reason="test",
            notify_progress=False,
        )

    posted_comments = [call.args[2] for call in mock_github_client.post_comment.call_args_list]
    assert not any("No plan file found" in body for body in posted_comments)


@pytest.mark.asyncio
async def test_does_not_repost_no_ticket_fidelity_report():
    """Do not post the no-ticket fidelity report more than once per PR."""

    mock_github_client = MagicMock()
    mock_github_client.post_comment = AsyncMock(return_value=12345)
    mock_github_client.edit_comment = AsyncMock()
    mock_github_client.post_review = AsyncMock()
    mock_github_client.reply_to_review_comment = AsyncMock()

    mock_pr_context = MagicMock()
    mock_pr_context.discussion_threads = []
    mock_pr_context.issue_comments = [
        DiscussionComment(
            id=111,
            author="baloo[bot]",
            body=(
                "<details>\n"
                "<summary>📋 Fidelity Report - ⏭️ Skipped</summary>\n\n"
                "**No ticket ID found in PR.**\n\n"
                "</details>"
            ),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source="issue_comment",
            is_baloo=True,
        )
    ]
    mock_pr_context.awaiting_response_threads = 0
    mock_pr_context.head_sha = "abc123"
    mock_pr_context.head_branch = "fix/fidelity-missing-report-dedupe"
    mock_pr_context.title = "Fix duplicate fidelity reports"
    mock_pr_context.description = ""
    mock_pr_context.diff = "+ added code"
    mock_github_client.get_pr_context = AsyncMock(return_value=mock_pr_context)

    mock_agent = MagicMock()
    mock_agent.review_pr = AsyncMock(
        return_value=ReviewResult(
            summary="Review complete",
            comments=[],
            approve=True,
            request_changes=False,
        )
    )

    with (
        patch("baloo.github.webhook_handler.GitHubAPIClient", return_value=mock_github_client),
        patch("baloo.agent.client.BalooAgent", return_value=mock_agent),
        patch("baloo.config.settings.settings.fidelity_enabled", True),
        patch("baloo.config.settings.settings.review_auto_approve", True),
        patch("baloo.github.webhook_handler.extract_ticket_id", return_value=None),
    ):
        await process_pr_review(
            repo_full_name="test/repo",
            pr_number=123,
            installation_id=456,
            trigger_reason="test",
            notify_progress=False,
        )

    posted_comments = [call.args[2] for call in mock_github_client.post_comment.call_args_list]
    assert not any("No ticket ID found" in body for body in posted_comments)


@pytest.mark.asyncio
async def test_does_not_repost_error_fidelity_report():
    """Do not post the fidelity error report more than once per PR."""

    mock_github_client = MagicMock()
    mock_github_client.post_comment = AsyncMock(return_value=12345)
    mock_github_client.edit_comment = AsyncMock()
    mock_github_client.post_review = AsyncMock()
    mock_github_client.reply_to_review_comment = AsyncMock()

    mock_pr_context = MagicMock()
    mock_pr_context.discussion_threads = []
    mock_pr_context.issue_comments = [
        DiscussionComment(
            id=111,
            author="baloo[bot]",
            body=(
                "<details>\n"
                "<summary>📋 Fidelity Report (DEN-123) - ⚠️ Error</summary>\n\n"
                "**Fidelity analysis encountered an error.**\n\n"
                "</details>"
            ),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source="issue_comment",
            is_baloo=True,
        )
    ]
    mock_pr_context.awaiting_response_threads = 0
    mock_pr_context.head_sha = "abc123"
    mock_pr_context.head_branch = "feat/DEN-123/add-feature"
    mock_pr_context.title = "Add new feature"
    mock_pr_context.description = "This PR adds a new feature"
    mock_pr_context.diff = "+ added code"
    mock_github_client.get_pr_context = AsyncMock(return_value=mock_pr_context)

    mock_agent = MagicMock()
    mock_agent.review_pr = AsyncMock(
        return_value=ReviewResult(
            summary="Review complete",
            comments=[],
            approve=True,
            request_changes=False,
        )
    )

    with (
        patch("baloo.github.webhook_handler.GitHubAPIClient", return_value=mock_github_client),
        patch("baloo.agent.client.BalooAgent", return_value=mock_agent),
        patch("baloo.config.settings.settings.fidelity_enabled", True),
        patch("baloo.config.settings.settings.review_auto_approve", True),
        patch("baloo.github.webhook_handler.extract_ticket_id", return_value="DEN-123"),
        patch(
            "baloo.github.webhook_handler.fetch_plan_content",
            AsyncMock(return_value="# Plan"),
        ),
        patch(
            "baloo.github.webhook_handler.analyze_fidelity",
            AsyncMock(return_value=None),
        ),
    ):
        await process_pr_review(
            repo_full_name="test/repo",
            pr_number=123,
            installation_id=456,
            trigger_reason="test",
            notify_progress=False,
        )

    posted_comments = [call.args[2] for call in mock_github_client.post_comment.call_args_list]
    assert not any("encountered an error" in body for body in posted_comments)


async def _process_review_with_existing_fidelity_comment(
    existing_comment_body: str,
    *,
    ticket_id: str | None,
    plan_content: str | None = None,
    fidelity_result: FidelityResult | None = None,
) -> list[str]:
    mock_github_client = MagicMock()
    mock_github_client.post_comment = AsyncMock(return_value=12345)
    mock_github_client.edit_comment = AsyncMock()
    mock_github_client.post_review = AsyncMock()
    mock_github_client.reply_to_review_comment = AsyncMock()

    mock_pr_context = MagicMock()
    mock_pr_context.discussion_threads = []
    mock_pr_context.issue_comments = [
        DiscussionComment(
            id=111,
            author="baloo[bot]",
            body=existing_comment_body,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source="issue_comment",
            is_baloo=True,
        )
    ]
    mock_pr_context.awaiting_response_threads = 0
    mock_pr_context.head_sha = "abc123"
    mock_pr_context.head_branch = "feat/DEN-123/add-feature"
    mock_pr_context.title = "Add new feature"
    mock_pr_context.description = "This PR adds a new feature"
    mock_pr_context.diff = "+ added code"
    mock_github_client.get_pr_context = AsyncMock(return_value=mock_pr_context)

    mock_agent = MagicMock()
    mock_agent.review_pr = AsyncMock(
        return_value=ReviewResult(
            summary="Review complete",
            comments=[],
            approve=True,
            request_changes=False,
        )
    )

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "baloo.github.webhook_handler.GitHubAPIClient",
                return_value=mock_github_client,
            )
        )
        stack.enter_context(patch("baloo.agent.client.BalooAgent", return_value=mock_agent))
        stack.enter_context(patch("baloo.config.settings.settings.fidelity_enabled", True))
        stack.enter_context(patch("baloo.config.settings.settings.review_auto_approve", True))
        stack.enter_context(
            patch("baloo.github.webhook_handler.extract_ticket_id", return_value=ticket_id)
        )
        if ticket_id:
            stack.enter_context(
                patch(
                    "baloo.github.webhook_handler.fetch_plan_content",
                    AsyncMock(return_value=plan_content),
                )
            )
        if ticket_id and plan_content:
            stack.enter_context(
                patch(
                    "baloo.github.webhook_handler.analyze_fidelity",
                    AsyncMock(return_value=fidelity_result),
                )
            )

        await process_pr_review(
            repo_full_name="test/repo",
            pr_number=123,
            installation_id=456,
            trigger_reason="test",
            notify_progress=False,
        )

    return [call.args[2] for call in mock_github_client.post_comment.call_args_list]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("existing_comment_body", "ticket_id", "plan_content", "forbidden_text"),
    [
        (
            (
                "<details>\n"
                "<summary>📋 Fidelity Report - ⏭️ Skipped</summary>\n\n"
                f"{NO_TICKET_FIDELITY_SENTINEL}\n\n"
                "**No ticket ID found in PR.**\n\n"
                "</details>"
            ),
            None,
            None,
            "No ticket ID found",
        ),
        (
            (
                "<details>\n"
                "<summary>📋 Fidelity Report (DEN-123) - ⏭️ Skipped</summary>\n\n"
                f"{MISSING_PLAN_FIDELITY_SENTINEL}\n\n"
                "**No plan file found at `docs/plans/DEN-123.md`**\n\n"
                "</details>"
            ),
            "DEN-123",
            None,
            "No plan file found",
        ),
        (
            (
                "<details>\n"
                "<summary>📋 Fidelity Report (DEN-123) - ⚠️ Error</summary>\n\n"
                f"{ERROR_FIDELITY_SENTINEL}\n\n"
                "**Fidelity analysis encountered an error.**\n\n"
                "</details>"
            ),
            "DEN-123",
            "# Plan",
            "encountered an error",
        ),
    ],
)
async def test_does_not_repost_sentinel_marked_static_fidelity_report(
    existing_comment_body: str,
    ticket_id: str | None,
    plan_content: str | None,
    forbidden_text: str,
):
    """Do not repost static fidelity reports when existing comments have sentinels."""
    posted_comments = await _process_review_with_existing_fidelity_comment(
        existing_comment_body,
        ticket_id=ticket_id,
        plan_content=plan_content,
        fidelity_result=None,
    )

    assert not any(forbidden_text in body for body in posted_comments)


@pytest.mark.asyncio
async def test_updates_progress_comment_when_no_actionable_findings():
    """Test that progress comment is updated when no actionable findings."""

    # Mock GitHub client
    mock_github_client = MagicMock()
    mock_github_client.post_comment = AsyncMock(return_value=12345)  # Return comment ID
    mock_github_client.edit_comment = AsyncMock()
    mock_github_client.post_review = AsyncMock()
    mock_github_client.reply_to_review_comment = AsyncMock()

    # Mock PR context with no discussion threads
    mock_pr_context = MagicMock()
    mock_pr_context.discussion_threads = []
    mock_pr_context.awaiting_response_threads = 0
    mock_pr_context.head_sha = "abc123"
    mock_github_client.get_pr_context = AsyncMock(return_value=mock_pr_context)

    # Mock agent that returns only LOW severity finding
    mock_agent = MagicMock()
    mock_review_result = ReviewResult(
        summary="Review complete",
        comments=[
            ReviewComment(
                path="test.py",
                line=1,
                body="Low severity observation",
                severity="LOW",
                category="Quality",
            )
        ],
        approve=True,
        request_changes=False,
    )
    mock_agent.review_pr = AsyncMock(return_value=mock_review_result)

    with (
        patch("baloo.github.webhook_handler.GitHubAPIClient", return_value=mock_github_client),
        patch("baloo.agent.client.BalooAgent", return_value=mock_agent),
        patch("baloo.config.settings.settings.review_auto_approve", False),
        patch("baloo.config.settings.settings.review_min_severity", "MEDIUM"),
    ):

        await process_pr_review(
            repo_full_name="test/repo",
            pr_number=123,
            installation_id=456,
            trigger_reason="test",
            notify_progress=True,  # Enable progress notification
        )

        # Verify progress comment was posted initially
        mock_github_client.post_comment.assert_called_once()

        # Verify progress comment was updated with completion status
        mock_github_client.edit_comment.assert_called_once()
        call_args = mock_github_client.edit_comment.call_args
        assert call_args[0][0] == "test/repo"
        assert call_args[0][1] == 12345  # The comment ID
        assert "No issues found" in call_args[0][2] or "review completed" in call_args[0][2].lower()


@pytest.mark.asyncio
async def test_posts_approval_when_auto_approve_enabled():
    """Test that approval review is posted when auto_approve=True."""

    # Mock GitHub client
    mock_github_client = MagicMock()
    mock_github_client.post_comment = AsyncMock()
    mock_github_client.post_review = AsyncMock()
    mock_github_client.reply_to_review_comment = AsyncMock()

    # Mock PR context with no discussion threads
    mock_pr_context = MagicMock()
    mock_pr_context.discussion_threads = []
    mock_pr_context.awaiting_response_threads = 0
    mock_pr_context.head_sha = "abc123"
    mock_github_client.get_pr_context = AsyncMock(return_value=mock_pr_context)

    # Mock agent that returns no findings
    mock_agent = MagicMock()
    mock_review_result = ReviewResult(
        summary="Review complete",
        comments=[],
        approve=True,
        request_changes=False,
    )
    mock_agent.review_pr = AsyncMock(return_value=mock_review_result)

    with (
        patch("baloo.github.webhook_handler.GitHubAPIClient", return_value=mock_github_client),
        patch("baloo.agent.client.BalooAgent", return_value=mock_agent),
        patch("baloo.config.settings.settings.review_auto_approve", True),
        patch("baloo.config.settings.settings.review_min_severity", "MEDIUM"),
    ):

        await process_pr_review(
            repo_full_name="test/repo",
            pr_number=123,
            installation_id=456,
            trigger_reason="test",
            notify_progress=False,
        )

        # Verify approval review was posted (not just a comment)
        mock_github_client.post_review.assert_called_once()
        call_args = mock_github_client.post_review.call_args
        assert call_args[0][0] == "test/repo"
        assert call_args[0][1] == 123
        review_result = call_args[0][2]
        assert review_result.approve is True
        assert review_result.request_changes is False


@pytest.mark.asyncio
async def test_approves_clean_review_with_high_fidelity_score():
    """Test that clean review with high fidelity score auto-approves even without auto_approve setting."""

    # Mock GitHub client
    mock_github_client = MagicMock()
    mock_github_client.post_comment = AsyncMock(return_value=12345)
    mock_github_client.edit_comment = AsyncMock()
    mock_github_client.post_review = AsyncMock()
    mock_github_client.reply_to_review_comment = AsyncMock()

    # Mock PR context with ticket in branch name
    mock_pr_context = MagicMock()
    mock_pr_context.discussion_threads = []
    mock_pr_context.awaiting_response_threads = 0
    mock_pr_context.head_sha = "abc123"
    mock_pr_context.head_branch = "feat/DEN-123/add-feature"
    mock_pr_context.title = "Add new feature"
    mock_pr_context.description = "This PR adds a new feature"
    mock_pr_context.diff = "+ added code"
    mock_github_client.get_pr_context = AsyncMock(return_value=mock_pr_context)

    # Mock agent that returns no findings (clean review)
    mock_agent = MagicMock()
    mock_review_result = ReviewResult(
        summary="Review complete",
        comments=[],
        approve=True,
        request_changes=False,
    )
    mock_agent.review_pr = AsyncMock(return_value=mock_review_result)

    # Mock fidelity analysis returning high score
    fidelity_result = FidelityResult(
        ticket_id="DEN-123",
        fidelity_score=95,  # High score (above 90 threshold)
        logic_summary="Implementation matches the plan perfectly",
        requirements=[],
        extras=[],
        discrepancies=[],
    )

    with (
        patch("baloo.github.webhook_handler.GitHubAPIClient", return_value=mock_github_client),
        patch("baloo.agent.client.BalooAgent", return_value=mock_agent),
        patch("baloo.config.settings.settings.review_auto_approve", False),
        patch("baloo.config.settings.settings.fidelity_enabled", True),
        patch("baloo.config.settings.settings.fidelity_approval_threshold", 90),
        patch(
            "baloo.github.webhook_handler.analyze_fidelity", AsyncMock(return_value=fidelity_result)
        ),
        patch("baloo.github.webhook_handler.extract_ticket_id", return_value="DEN-123"),
        patch(
            "baloo.github.webhook_handler.fetch_plan_content",
            AsyncMock(return_value="# Plan content"),
        ),
    ):

        await process_pr_review(
            repo_full_name="test/repo",
            pr_number=123,
            installation_id=456,
            trigger_reason="test",
            notify_progress=True,
        )

        # Verify approval review was posted even though auto_approve is False
        mock_github_client.post_review.assert_called_once()
        call_args = mock_github_client.post_review.call_args
        review_result = call_args[0][2]
        assert review_result.approve is True
        assert review_result.request_changes is False


@pytest.mark.asyncio
async def test_approves_with_medium_issues_when_high_fidelity():
    """Test that MEDIUM issues do NOT prevent fidelity-based auto-approval."""

    # Mock GitHub client
    mock_github_client = MagicMock()
    mock_github_client.post_comment = AsyncMock(return_value=12345)
    mock_github_client.edit_comment = AsyncMock()
    mock_github_client.post_review = AsyncMock()
    mock_github_client.reply_to_review_comment = AsyncMock()

    # Mock PR context with ticket in branch name
    mock_pr_context = MagicMock()
    mock_pr_context.discussion_threads = []
    mock_pr_context.awaiting_response_threads = 0
    mock_pr_context.head_sha = "abc123"
    mock_pr_context.head_branch = "feat/DEN-123/add-feature"
    mock_pr_context.title = "Add new feature"
    mock_pr_context.description = "This PR adds a new feature"
    mock_pr_context.diff = "+ added code"
    mock_github_client.get_pr_context = AsyncMock(return_value=mock_pr_context)

    # Mock agent that returns MEDIUM severity finding
    # Note: body must not contain low-confidence patterns like "consider", "might", "maybe"
    mock_agent = MagicMock()
    mock_review_result = ReviewResult(
        summary="Review complete",
        comments=[
            ReviewComment(
                path="test.py",
                line=10,
                body="This function has a performance issue that should be addressed",
                severity="MEDIUM",
                category="Performance",
            )
        ],
        approve=False,
        request_changes=False,
    )
    mock_agent.review_pr = AsyncMock(return_value=mock_review_result)

    # Mock fidelity analysis returning high score
    fidelity_result = FidelityResult(
        ticket_id="DEN-123",
        fidelity_score=95,  # High score (above 90 threshold)
        logic_summary="Implementation matches the plan perfectly",
        requirements=[],
        extras=[],
        discrepancies=[],
    )

    with (
        patch("baloo.github.webhook_handler.GitHubAPIClient", return_value=mock_github_client),
        patch("baloo.agent.client.BalooAgent", return_value=mock_agent),
        patch("baloo.config.settings.settings.review_auto_approve", False),
        patch("baloo.config.settings.settings.review_min_severity", "MEDIUM"),
        patch("baloo.config.settings.settings.fidelity_enabled", True),
        patch("baloo.config.settings.settings.fidelity_approval_threshold", 90),
        patch("baloo.config.settings.settings.review_use_checks_api", False),
        patch(
            "baloo.github.webhook_handler.analyze_fidelity", AsyncMock(return_value=fidelity_result)
        ),
        patch("baloo.github.webhook_handler.extract_ticket_id", return_value="DEN-123"),
        patch(
            "baloo.github.webhook_handler.fetch_plan_content",
            AsyncMock(return_value="# Plan content"),
        ),
    ):

        await process_pr_review(
            repo_full_name="test/repo",
            pr_number=123,
            installation_id=456,
            trigger_reason="test",
            notify_progress=True,
        )

        # Verify approval review was posted (MEDIUM issues don't prevent fidelity-based approval)
        mock_github_client.post_review.assert_called()
        approval_calls = [
            call
            for call in mock_github_client.post_review.call_args_list
            if call[0][2].approve is True
        ]
        assert len(approval_calls) == 1, "Should approve when high fidelity despite MEDIUM issues"


@pytest.mark.asyncio
async def test_does_not_approve_with_low_fidelity_score():
    """Test that low fidelity score prevents auto-approval when auto_approve is False."""

    # Mock GitHub client
    mock_github_client = MagicMock()
    mock_github_client.post_comment = AsyncMock(return_value=12345)
    mock_github_client.edit_comment = AsyncMock()
    mock_github_client.post_review = AsyncMock()
    mock_github_client.reply_to_review_comment = AsyncMock()

    # Mock PR context with ticket in branch name
    mock_pr_context = MagicMock()
    mock_pr_context.discussion_threads = []
    mock_pr_context.awaiting_response_threads = 0
    mock_pr_context.head_sha = "abc123"
    mock_pr_context.head_branch = "feat/DEN-123/add-feature"
    mock_pr_context.title = "Add new feature"
    mock_pr_context.description = "This PR adds a new feature"
    mock_pr_context.diff = "+ added code"
    mock_github_client.get_pr_context = AsyncMock(return_value=mock_pr_context)

    # Mock agent that returns no findings (clean review)
    mock_agent = MagicMock()
    mock_review_result = ReviewResult(
        summary="Review complete",
        comments=[],
        approve=True,
        request_changes=False,
    )
    mock_agent.review_pr = AsyncMock(return_value=mock_review_result)

    # Mock fidelity analysis returning LOW score
    fidelity_result = FidelityResult(
        ticket_id="DEN-123",
        fidelity_score=60,  # Low score (below 90 threshold)
        logic_summary="Implementation deviates from the plan",
        requirements=[],
        extras=[],
        discrepancies=[],
    )

    with (
        patch("baloo.github.webhook_handler.GitHubAPIClient", return_value=mock_github_client),
        patch("baloo.agent.client.BalooAgent", return_value=mock_agent),
        patch("baloo.config.settings.settings.review_auto_approve", False),
        patch("baloo.config.settings.settings.fidelity_enabled", True),
        patch("baloo.config.settings.settings.fidelity_approval_threshold", 90),
        patch(
            "baloo.github.webhook_handler.analyze_fidelity", AsyncMock(return_value=fidelity_result)
        ),
        patch("baloo.github.webhook_handler.extract_ticket_id", return_value="DEN-123"),
        patch(
            "baloo.github.webhook_handler.fetch_plan_content",
            AsyncMock(return_value="# Plan content"),
        ),
    ):

        await process_pr_review(
            repo_full_name="test/repo",
            pr_number=123,
            installation_id=456,
            trigger_reason="test",
            notify_progress=True,
        )

        # Verify approval review was NOT posted (low fidelity prevents approval)
        # With auto_approve=False and low fidelity, no approval should happen
        calls = mock_github_client.post_review.call_args_list
        for call in calls:
            review_result = call[0][2]
            assert review_result.approve is False
