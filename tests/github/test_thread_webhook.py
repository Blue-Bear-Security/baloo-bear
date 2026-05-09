"""Tests for the thread reply webhook handler."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from baloo.github.webhook_handler import app


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def _make_review_comment_payload(
    *,
    comment_body: str = "This uses parameterized queries",
    comment_author: str = "alice",
    in_reply_to_id: int | None = 100,
    comment_id: int = 200,
    path: str = "src/auth.py",
    line: int = 42,
    pr_number: int = 1,
    repo: str = "org/repo",
    installation_id: int = 1,
) -> dict:
    return {
        "action": "created",
        "comment": {
            "id": comment_id,
            "body": comment_body,
            "user": {"login": comment_author, "id": 1, "avatar_url": "", "html_url": ""},
            "in_reply_to_id": in_reply_to_id,
            "path": path,
            "line": line,
            "original_line": line,
            "html_url": f"https://github.com/{repo}/pull/{pr_number}#discussion_r{comment_id}",
            "created_at": "2026-05-09T12:00:00Z",
        },
        "pull_request": {
            "number": pr_number,
            "title": "Test PR",
            "body": "",
            "state": "open",
            "html_url": f"https://github.com/{repo}/pull/{pr_number}",
            "user": {"login": "dev", "id": 2, "avatar_url": "", "html_url": ""},
            "head": {"sha": "abc123", "ref": "feat/test"},
            "base": {"ref": "main"},
            "merged": False,
            "draft": False,
        },
        "repository": {
            "id": 1,
            "name": "repo",
            "full_name": repo,
            "owner": {"login": "org", "id": 1, "avatar_url": "", "html_url": ""},
            "html_url": f"https://github.com/{repo}",
            "default_branch": "main",
        },
        "installation": {"id": installation_id},
        "sender": {"login": comment_author, "id": 1, "avatar_url": "", "html_url": ""},
    }


@patch("baloo.github.webhook_handler.verify_webhook_signature", return_value=True)
@patch("baloo.github.webhook_handler.settings")
def test_thread_comment_ignored_when_disabled(mock_settings, mock_verify, client):
    """Thread comments are ignored when thread agent is disabled."""
    mock_settings.thread_agent_enabled = False

    response = client.post(
        "/webhook",
        json=_make_review_comment_payload(),
        headers={
            "X-GitHub-Event": "pull_request_review_comment",
            "X-Hub-Signature-256": "sha256=fake",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ignored"


@patch("baloo.github.webhook_handler.verify_webhook_signature", return_value=True)
@patch("baloo.github.webhook_handler.settings")
def test_thread_comment_ignored_when_no_reply_to(mock_settings, mock_verify, client):
    """Comments that are not replies to an existing comment are ignored."""
    mock_settings.thread_agent_enabled = True

    payload = _make_review_comment_payload(in_reply_to_id=None)

    response = client.post(
        "/webhook",
        json=payload,
        headers={
            "X-GitHub-Event": "pull_request_review_comment",
            "X-Hub-Signature-256": "sha256=fake",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ignored"


@patch("baloo.github.webhook_handler.verify_webhook_signature", return_value=True)
@patch("baloo.github.webhook_handler.settings")
def test_thread_comment_ignored_when_author_is_baloo(mock_settings, mock_verify, client):
    """Baloo's own comments are ignored (no self-replies)."""
    mock_settings.thread_agent_enabled = True

    payload = _make_review_comment_payload(comment_author="baloo-bear[bot]")

    response = client.post(
        "/webhook",
        json=payload,
        headers={
            "X-GitHub-Event": "pull_request_review_comment",
            "X-Hub-Signature-256": "sha256=fake",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ignored"
