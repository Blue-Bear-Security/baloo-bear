"""Tests for redundant review cancellation."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from baloo.github.webhook_handler import active_reviews, app


def create_payload(repo_name: str, pr_number: int, head_sha: str):
    """Create a valid PullRequestWebhookPayload dictionary."""
    repo_short_name = repo_name.split("/")[1]

    user_data = {
        "login": "testuser",
        "id": 1,
        "avatar_url": "https://example.com/avatar.png",
        "html_url": "https://github.com/testuser",
    }

    return {
        "action": "synchronize",
        "number": pr_number,
        "pull_request": {
            "number": pr_number,
            "title": "Test PR",
            "state": "open",
            "html_url": f"https://github.com/{repo_name}/pull/{pr_number}",
            "user": user_data,
            "head": {"sha": head_sha},
            "base": {"ref": "main"},
            "draft": False,
        },
        "repository": {
            "id": 123,
            "name": repo_short_name,
            "full_name": repo_name,
            "owner": user_data,
            "html_url": f"https://github.com/{repo_name}",
            "default_branch": "main",
        },
        "installation": {"id": 456},
        "sender": user_data,
    }


@pytest.mark.asyncio
async def test_cancels_redundant_review():
    """Test that a new commit on the same PR cancels the ongoing review."""

    repo_name = "test/repo"
    pr_number = 123

    # Event loop for async coordination
    task_started_event = asyncio.Event()
    task_cancelled_event = asyncio.Event()

    async def mock_process_review(*args, **kwargs):
        task_started_event.set()
        try:
            # Simulate long review
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            task_cancelled_event.set()
            raise

    # Clear active reviews before test
    active_reviews.clear()

    # Mock dependencies
    # We patch process_pr_review in webhook_handler where it is used
    with (
        patch("baloo.github.webhook_handler.verify_webhook_signature", return_value=True),
        patch(
            "baloo.github.webhook_handler._validate_webhook_security",
            new=AsyncMock(return_value=None),
        ),
        patch("baloo.github.webhook_handler.process_pr_review", side_effect=mock_process_review),
        patch("baloo.github.webhook_handler.GitHubAPIClient") as mock_github_client_class,
    ):

        # Setup mock GitHub client instance
        mock_github = MagicMock()
        mock_github.is_merge_or_sync_commit = AsyncMock(return_value=(False, ""))
        mock_github.__aenter__ = AsyncMock(return_value=mock_github)
        mock_github.__aexit__ = AsyncMock(return_value=None)
        mock_github_client_class.return_value = mock_github

        # Use AsyncClient with ASGITransport to avoid Task cancellation on response
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:

            # 1. Trigger first review
            payload1 = create_payload(repo_name, pr_number, "sha1")

            # First request starts the task
            await client.post(
                "/webhook",
                json=payload1,
                headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": "sha256=test"},
            )

            # Wait for task to actually start
            try:
                await asyncio.wait_for(task_started_event.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pytest.fail("Task failed to start or event not set")

            assert (repo_name, pr_number) in active_reviews
            task1 = active_reviews[(repo_name, pr_number)]

            # Check if task1 is actually running
            assert not task1.done(), f"Task finished prematurely: {task1}"

            # 2. Trigger second review for SAME PR
            payload2 = create_payload(repo_name, pr_number, "sha2")

            # Second request should cancel the first task
            await client.post(
                "/webhook",
                json=payload2,
                headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": "sha256=test"},
            )

            # Wait for first task to be cancelled
            try:
                await asyncio.wait_for(task_cancelled_event.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pytest.fail("First task was not cancelled by second request")

            assert task1.cancelled() or task1.done()

            # Verify second task is now the active one
            task2 = active_reviews[(repo_name, pr_number)]
            assert task2 != task1

            # Cleanup: cancel second task
            task2.cancel()
            try:
                await task2
            except asyncio.CancelledError:
                pass
