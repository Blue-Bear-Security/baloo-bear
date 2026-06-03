"""Tests for the webhook_handler.py FastAPI endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from baloo.github.webhook_handler import app, lifespan


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def _pr_payload(action: str = "opened", draft: bool = False) -> dict:
    return {
        "action": action,
        "number": 1,
        "pull_request": {
            "number": 1,
            "title": "Test PR",
            "body": "",
            "state": "open",
            "html_url": "https://github.com/org/repo/pull/1",
            "user": {"login": "dev", "id": 1, "avatar_url": "", "html_url": ""},
            "head": {"sha": "abc123", "ref": "feat/test"},
            "base": {"ref": "main"},
            "merged": False,
            "draft": draft,
        },
        "repository": {
            "id": 1,
            "name": "repo",
            "full_name": "org/repo",
            "owner": {"login": "org", "id": 1, "avatar_url": "", "html_url": ""},
            "html_url": "https://github.com/org/repo",
            "private": False,
            "default_branch": "main",
        },
        "installation": {"id": 1},
        "sender": {"login": "dev", "id": 1, "avatar_url": "", "html_url": ""},
    }


def _post_webhook(client, payload: dict, event: str = "pull_request"):
    import json

    body = json.dumps(payload).encode()
    with (
        patch("baloo.github.webhook_handler.verify_webhook_signature", return_value=True),
        patch(
            "baloo.github.webhook_handler._validate_webhook_security",
            new=AsyncMock(return_value=None),
        ),
    ):
        return client.post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": event,
                "X-Hub-Signature-256": "sha256=skip",
            },
        )


class TestRootEndpoint:
    def test_root_returns_healthy(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json() == {"status": "healthy", "service": "baloo"}


class TestWebhookSignature:
    def test_invalid_signature_returns_403(self, client):
        import json

        body = json.dumps(_pr_payload()).encode()
        with patch("baloo.github.webhook_handler.verify_webhook_signature", return_value=False):
            resp = client.post(
                "/webhook",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Event": "pull_request",
                    "X-Hub-Signature-256": "sha256=invalidsignature",
                },
            )
        assert resp.status_code == 403


class TestWebhookSecuritySkip:
    def test_security_validation_skip_is_forwarded(self, client):
        """When _validate_webhook_security returns a skip dict, it is returned as-is."""
        import json

        payload = _pr_payload()
        body = json.dumps(payload).encode()

        with (
            patch("baloo.github.webhook_handler.verify_webhook_signature", return_value=True),
            patch(
                "baloo.github.webhook_handler._validate_webhook_security",
                new=AsyncMock(return_value={"status": "skipped", "reason": "test"}),
            ),
        ):
            resp = client.post(
                "/webhook",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Event": "pull_request",
                    "X-Hub-Signature-256": "sha256=skip",
                },
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"


class TestPullRequestActionRouting:
    def test_draft_pr_is_skipped(self, client):
        payload = _pr_payload(action="opened", draft=True)
        resp = _post_webhook(client, payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "skipped"
        assert data["reason"] == "draft PR"

    def test_synchronize_merge_commit_is_skipped(self, client):
        payload = _pr_payload(action="synchronize")
        payload["before"] = "base123"

        mock_gc = MagicMock()
        mock_gc.__aenter__ = AsyncMock(return_value=mock_gc)
        mock_gc.__aexit__ = AsyncMock(return_value=False)
        mock_gc.is_merge_or_sync_commit = AsyncMock(return_value=(True, "merge commit"))

        with patch("baloo.github.webhook_handler.GitHubAPIClient", return_value=mock_gc):
            resp = _post_webhook(client, payload)

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "skipped"

    def test_unsupported_action_is_ignored(self, client):
        payload = _pr_payload(action="labeled")
        resp = _post_webhook(client, payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ignored"
        assert data["action"] == "labeled"

    def test_pr_closed_not_merged_is_ignored(self, client):
        payload = _pr_payload(action="closed")
        payload["pull_request"]["merged"] = False
        resp = _post_webhook(client, payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ignored"
        assert data["action"] == "closed"

    def test_pr_closed_merged_triggers_labeling(self, client):
        payload = _pr_payload(action="closed")
        payload["pull_request"]["merged"] = True
        resp = _post_webhook(client, payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "labeling_outcomes"


class TestPullRequestReviewCommentRouting:
    def _make_review_comment_payload(
        self,
        *,
        action: str = "created",
        author: str = "alice",
        in_reply_to_id: int | None = 100,
        body: str = "Looks good",
    ) -> dict:
        return {
            "action": action,
            "comment": {
                "id": 200,
                "body": body,
                "user": {"login": author, "id": 1, "avatar_url": "", "html_url": ""},
                "in_reply_to_id": in_reply_to_id,
                "path": "src/auth.py",
                "line": 42,
                "original_line": 42,
                "html_url": "https://github.com/org/repo/pull/1#discussion_r200",
                "created_at": "2026-05-29T12:00:00Z",
            },
            "pull_request": {
                "number": 1,
                "title": "Test PR",
                "body": "",
                "state": "open",
                "html_url": "https://github.com/org/repo/pull/1",
                "user": {"login": "dev", "id": 2, "avatar_url": "", "html_url": ""},
                "head": {"sha": "abc123", "ref": "feat/test"},
                "base": {"ref": "main"},
                "merged": False,
                "draft": False,
            },
            "repository": {
                "id": 1,
                "name": "repo",
                "full_name": "org/repo",
                "owner": {"login": "org", "id": 1, "avatar_url": "", "html_url": ""},
                "html_url": "https://github.com/org/repo",
                "private": False,
                "default_branch": "main",
            },
            "installation": {"id": 1},
            "sender": {"login": author, "id": 1, "avatar_url": "", "html_url": ""},
        }

    def test_thread_agent_disabled_returns_ignored(self, client):
        payload = self._make_review_comment_payload()
        mock_settings = MagicMock()
        mock_settings.thread_agent_enabled = False
        with patch("baloo.github.webhook_handler.settings", mock_settings):
            resp = _post_webhook(client, payload, event="pull_request_review_comment")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ignored"
        assert "thread agent disabled" in data["reason"]

    def test_thread_reply_queued(self, client):
        payload = self._make_review_comment_payload(author="developer", body="I fixed it")
        mock_settings = MagicMock()
        mock_settings.thread_agent_enabled = True
        with patch("baloo.github.webhook_handler.settings", mock_settings):
            resp = _post_webhook(client, payload, event="pull_request_review_comment")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"

    def test_review_comment_edit_action_is_ignored(self, client):
        payload = self._make_review_comment_payload(action="edited")
        resp = _post_webhook(client, payload, event="pull_request_review_comment")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ignored"
        assert "action=edited" in data["reason"]


class TestPullRequestMalformedPayload:
    def test_malformed_pr_payload_returns_500(self, client):
        """A pull_request event with a missing required field raises 500."""
        # Missing most required fields — PullRequestWebhookPayload(**payload) will raise
        payload = {
            "action": "opened",
            "number": 1,
            "pull_request": {},  # Missing required nested fields
            "repository": {"id": 1, "name": "repo", "full_name": "org/repo"},
            "installation": {"id": 1},
        }
        import json

        body = json.dumps(payload).encode()
        with (
            patch("baloo.github.webhook_handler.verify_webhook_signature", return_value=True),
            patch(
                "baloo.github.webhook_handler._validate_webhook_security",
                new=AsyncMock(return_value=None),
            ),
        ):
            resp = client.post(
                "/webhook",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Event": "pull_request",
                    "X-Hub-Signature-256": "sha256=skip",
                },
            )
        assert resp.status_code == 500


class TestUnsupportedEvents:
    def test_issue_comment_event_is_ignored(self, client):
        payload = {"installation": {"id": 1}, "repository": {"full_name": "org/repo"}}
        resp = _post_webhook(client, payload, event="issue_comment")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ignored"

    def test_pull_request_review_event_is_ignored(self, client):
        payload = {"installation": {"id": 1}, "repository": {"full_name": "org/repo"}}
        resp = _post_webhook(client, payload, event="pull_request_review")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ignored"

    def test_unknown_event_type_is_ignored(self, client):
        payload = {"installation": {"id": 1}, "repository": {"full_name": "org/repo"}}
        resp = _post_webhook(client, payload, event="push")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ignored"
        assert data["event"] == "push"


class TestLifespan:
    @pytest.mark.asyncio
    async def test_lifespan_initializes_db_when_enabled_with_url(self):
        with (
            patch("baloo.github.webhook_handler.init_db", new=AsyncMock()) as mock_init,
            patch("baloo.github.webhook_handler.close_db", new=AsyncMock()) as mock_close,
            patch("baloo.github.webhook_handler.settings") as mock_settings,
        ):
            mock_settings.database_enabled = True
            mock_settings.database_url = "postgresql+asyncpg://user:pass@localhost/db"
            async with lifespan(app):
                pass

        mock_init.assert_called_once()
        mock_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_logs_warning_when_db_enabled_but_no_url(self):
        with (
            patch("baloo.github.webhook_handler.init_db", new=AsyncMock()) as mock_init,
            patch("baloo.github.webhook_handler.close_db", new=AsyncMock()),
            patch("baloo.github.webhook_handler.settings") as mock_settings,
        ):
            mock_settings.database_enabled = True
            mock_settings.database_url = ""
            async with lifespan(app):
                pass

        mock_init.assert_not_called()

    @pytest.mark.asyncio
    async def test_lifespan_skips_db_when_disabled(self):
        with (
            patch("baloo.github.webhook_handler.init_db", new=AsyncMock()) as mock_init,
            patch("baloo.github.webhook_handler.close_db", new=AsyncMock()) as mock_close,
            patch("baloo.github.webhook_handler.settings") as mock_settings,
        ):
            mock_settings.database_enabled = False
            mock_settings.database_url = ""
            async with lifespan(app):
                pass

        mock_init.assert_not_called()
        mock_close.assert_not_called()
