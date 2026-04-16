"""Tests for webhook handler completion messages."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from baloo.fidelity.models import FidelityResult
from baloo.github.models import ReviewComment, ReviewResult
from baloo.github.webhook_handler import process_pr_review


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
