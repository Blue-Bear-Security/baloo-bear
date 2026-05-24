"""Tests for webhook handler PR merge -> outcome labeling integration."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from baloo.github.webhook_handler import app

_USER = {
    "login": "octocat",
    "id": 1,
    "avatar_url": "https://github.com/images/error/octocat.gif",
    "html_url": "https://github.com/octocat",
}

_REPOSITORY = {
    "id": 1296269,
    "name": "repo",
    "full_name": "owner/repo",
    "owner": _USER,
    "html_url": "https://github.com/owner/repo",
    "default_branch": "main",
}

MERGED_PAYLOAD = {
    "action": "closed",
    "number": 42,
    "repository": _REPOSITORY,
    "installation": {"id": 999},
    "pull_request": {
        "number": 42,
        "title": "My PR",
        "html_url": "https://github.com/owner/repo/pull/42",
        "draft": False,
        "merged": True,
        "head": {"sha": "abc123", "ref": "feat/my-feature"},
        "base": {"sha": "def456", "ref": "main"},
        "user": _USER,
        "body": None,
        "state": "closed",
    },
    "sender": _USER,
}

CLOSED_NOT_MERGED_PAYLOAD = {
    **MERGED_PAYLOAD,
    "pull_request": {
        **MERGED_PAYLOAD["pull_request"],
        "merged": False,
    },
}


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=True)


def _webhook_headers(body: bytes) -> dict:
    return {
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": "sha256=dummy",
        "Content-Type": "application/json",
    }


def test_merged_pr_triggers_label_pr_outcomes(client):
    """A merged PR should fire label_pr_outcomes as a background task."""
    body = json.dumps(MERGED_PAYLOAD).encode()

    with (
        patch(
            "baloo.github.webhook_handler.verify_webhook_signature",
            return_value=True,
        ),
        patch(
            "baloo.github.webhook_handler._validate_webhook_security",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "baloo.github.webhook_handler.label_pr_outcomes",
            new_callable=AsyncMock,
        ) as mock_label,
    ):
        response = client.post("/webhook", content=body, headers=_webhook_headers(body))

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "labeling_outcomes"
    assert data["pr"] == 42
    mock_label.assert_called_once_with("owner/repo", 42, 999)


def test_closed_not_merged_does_not_trigger_labeling(client):
    """A closed-but-not-merged PR should NOT trigger outcome labeling."""
    body = json.dumps(CLOSED_NOT_MERGED_PAYLOAD).encode()

    with (
        patch(
            "baloo.github.webhook_handler.verify_webhook_signature",
            return_value=True,
        ),
        patch(
            "baloo.github.webhook_handler._validate_webhook_security",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "baloo.github.webhook_handler.label_pr_outcomes",
            new_callable=AsyncMock,
        ) as mock_label,
    ):
        response = client.post("/webhook", content=body, headers=_webhook_headers(body))

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ignored"
    assert data["reason"] == "not merged"
    mock_label.assert_not_called()
