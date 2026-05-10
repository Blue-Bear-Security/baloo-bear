"""Integration test for the full thread reply flow."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from baloo.github.webhook_handler import _process_thread_reply


@pytest.mark.asyncio
async def test_process_thread_reply_concede_writes_signal():
    """Full flow: developer disagrees validly -> Baloo concedes -> feedback signal written."""
    mock_client = AsyncMock()

    # Mock fetch_review_comments: return a Baloo finding + developer reply
    mock_client.fetch_review_comments.return_value = [
        {
            "id": 100,
            "body": "**[HIGH] Silent Failures** - except pass swallows errors",
            "user": {"login": "baloo-bear[bot]"},
            "path": "app/retry.py",
            "line": 15,
            "original_line": 15,
            "created_at": "2026-05-09T10:00:00Z",
            "updated_at": "2026-05-09T10:00:00Z",
            "html_url": "https://github.com/org/repo/pull/1#discussion_r100",
        },
        {
            "id": 200,
            "body": "This is intentional - retry loops need to swallow transient errors",
            "user": {"login": "alice"},
            "in_reply_to_id": 100,
            "path": "app/retry.py",
            "line": 15,
            "original_line": 15,
            "created_at": "2026-05-09T11:00:00Z",
            "updated_at": "2026-05-09T11:00:00Z",
            "html_url": "https://github.com/org/repo/pull/1#discussion_r200",
        },
    ]

    # Mock get_file_content: return some code
    mock_client.get_file_content.return_value = (
        "def retry(fn):\n"
        "    for _ in range(3):\n"
        "        try:\n"
        "            return fn()\n"
        "        except Exception:\n"
        "            pass\n"
        "    raise RuntimeError('retries exhausted')\n"
    )

    mock_client.reply_to_review_comment.return_value = True

    # Mock the ThreadAgent to return a concession
    mock_result = MagicMock()
    mock_result.classification = "disagreed_valid"
    mock_result.reply = "Got it, makes sense for retry loops."
    mock_result.feedback_signal = {
        "pattern": "except pass in retry loops is intentional",
        "category": "Silent Failures",
        "file_glob": "app/retry*.py",
    }

    with (
        patch("baloo.github.webhook_handler.GitHubAPIClient", return_value=mock_client),
        patch("baloo.github.webhook_handler.settings") as mock_settings,
        patch(
            "baloo.github.webhook_handler.get_thread_agent_semaphore",
            return_value=asyncio.Semaphore(3),
        ),
        patch(
            "baloo.agent.thread_agent.ThreadAgent.classify",
            new_callable=AsyncMock,
            return_value=mock_result,
        ),
        patch(
            "baloo.db.feedback_service.FeedbackService.write_signal", new_callable=AsyncMock
        ) as mock_write,
    ):
        mock_settings.thread_agent_max_replies = 3

        await _process_thread_reply(
            repo_full_name="org/repo",
            pr_number=1,
            installation_id=1,
            comment_data={
                "id": 200,
                "body": "This is intentional",
                "user": {"login": "alice"},
                "path": "app/retry.py",
                "line": 15,
                "original_line": 15,
                "html_url": "https://github.com/org/repo/pull/1#discussion_r200",
            },
            in_reply_to_id=100,
            head_sha="abc123",
        )

    # Verify reply was posted
    mock_client.reply_to_review_comment.assert_called_once_with(
        "org/repo", 1, 100, "Got it, makes sense for retry loops."
    )

    # Verify feedback signal was written
    mock_write.assert_called_once()
    call_kwargs = mock_write.call_args.kwargs
    assert call_kwargs["repo"] == "org/repo"
    assert call_kwargs["pattern"] == "except pass in retry loops is intentional"
    assert call_kwargs["category"] == "Silent Failures"
    assert call_kwargs["developer"] == "alice"


@pytest.mark.asyncio
async def test_process_thread_reply_escalation_cap():
    """Thread with too many Baloo messages is skipped (escalation)."""
    mock_client = AsyncMock()

    # 3 Baloo messages already in thread (original + 2 replies)
    mock_client.fetch_review_comments.return_value = [
        {
            "id": 100,
            "body": "Finding",
            "user": {"login": "baloo-bear[bot]"},
            "path": "f.py",
            "line": 1,
            "original_line": 1,
            "created_at": "2026-05-09T10:00:00Z",
            "updated_at": "2026-05-09T10:00:00Z",
        },
        {
            "id": 101,
            "body": "reply1",
            "user": {"login": "dev"},
            "in_reply_to_id": 100,
            "path": "f.py",
            "line": 1,
            "original_line": 1,
            "created_at": "2026-05-09T10:01:00Z",
            "updated_at": "2026-05-09T10:01:00Z",
        },
        {
            "id": 102,
            "body": "Baloo reply1",
            "user": {"login": "baloo-bear[bot]"},
            "in_reply_to_id": 100,
            "path": "f.py",
            "line": 1,
            "original_line": 1,
            "created_at": "2026-05-09T10:02:00Z",
            "updated_at": "2026-05-09T10:02:00Z",
        },
        {
            "id": 103,
            "body": "reply2",
            "user": {"login": "dev"},
            "in_reply_to_id": 100,
            "path": "f.py",
            "line": 1,
            "original_line": 1,
            "created_at": "2026-05-09T10:03:00Z",
            "updated_at": "2026-05-09T10:03:00Z",
        },
        {
            "id": 104,
            "body": "Baloo reply2",
            "user": {"login": "baloo-bear[bot]"},
            "in_reply_to_id": 100,
            "path": "f.py",
            "line": 1,
            "original_line": 1,
            "created_at": "2026-05-09T10:04:00Z",
            "updated_at": "2026-05-09T10:04:00Z",
        },
        {
            "id": 105,
            "body": "reply3",
            "user": {"login": "dev"},
            "in_reply_to_id": 100,
            "path": "f.py",
            "line": 1,
            "original_line": 1,
            "created_at": "2026-05-09T10:05:00Z",
            "updated_at": "2026-05-09T10:05:00Z",
        },
    ]

    with (
        patch("baloo.github.webhook_handler.GitHubAPIClient", return_value=mock_client),
        patch("baloo.github.webhook_handler.settings") as mock_settings,
        patch(
            "baloo.github.webhook_handler.get_thread_agent_semaphore",
            return_value=asyncio.Semaphore(3),
        ),
    ):
        mock_settings.thread_agent_max_replies = 3

        await _process_thread_reply(
            repo_full_name="org/repo",
            pr_number=1,
            installation_id=1,
            comment_data={
                "id": 105,
                "body": "reply3",
                "user": {"login": "dev"},
                "path": "f.py",
                "line": 1,
            },
            in_reply_to_id=100,
            head_sha="abc123",
        )

    # No reply should be posted — escalation cap hit
    mock_client.reply_to_review_comment.assert_not_called()
