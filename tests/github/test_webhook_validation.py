"""Tests for the webhook security validation chain."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


class TestValidateWebhookSecurity:
    @pytest.mark.asyncio
    async def test_raises_400_when_installation_id_missing(self):
        from baloo.github.webhook_handler import _validate_webhook_security

        with pytest.raises(HTTPException) as exc_info:
            await _validate_webhook_security(None, "org/repo")

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_returns_skip_when_installation_id_does_not_match_configured(self, monkeypatch):
        monkeypatch.setenv("INSTALLATION_ID", "111")
        from baloo.github.webhook_handler import _validate_webhook_security

        result = await _validate_webhook_security(999, "org/repo")

        assert result == {
            "status": "skipped",
            "reason": "installation not configured for this broker",
        }

    @pytest.mark.asyncio
    async def test_passes_when_installation_id_matches_configured(self, monkeypatch):
        monkeypatch.setenv("INSTALLATION_ID", "111")

        with (
            patch(
                "baloo.github.auth.GitHubAuth.get_installation_token",
                return_value="tok",
            ),
            patch(
                "baloo.github.webhook_handler.verify_repo_belongs_to_installation",
                new=AsyncMock(return_value=True),
            ),
        ):
            from baloo.github.webhook_handler import _validate_webhook_security

            result = await _validate_webhook_security(111, "org/repo")

        assert result is None

    @pytest.mark.asyncio
    async def test_passes_when_no_installation_id_configured(self, monkeypatch):
        monkeypatch.setenv("INSTALLATION_ID", "")

        with (
            patch(
                "baloo.github.auth.GitHubAuth.get_installation_token",
                return_value="tok",
            ),
            patch(
                "baloo.github.webhook_handler.verify_repo_belongs_to_installation",
                new=AsyncMock(return_value=True),
            ),
        ):
            from baloo.github.webhook_handler import _validate_webhook_security

            result = await _validate_webhook_security(999, "org/repo")

        assert result is None

    @pytest.mark.asyncio
    async def test_raises_403_when_installation_token_fetch_fails(self, monkeypatch):
        import httpx

        monkeypatch.setenv("INSTALLATION_ID", "")

        def raise_http_error(self, iid):
            raise httpx.HTTPStatusError("404", request=MagicMock(), response=MagicMock())

        with patch("baloo.github.auth.GitHubAuth.get_installation_token", raise_http_error):
            from baloo.github.webhook_handler import _validate_webhook_security

            with pytest.raises(HTTPException) as exc_info:
                await _validate_webhook_security(999, "org/repo")

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_raises_403_when_repo_not_in_installation(self, monkeypatch):
        monkeypatch.setenv("INSTALLATION_ID", "")

        with (
            patch(
                "baloo.github.auth.GitHubAuth.get_installation_token",
                return_value="tok",
            ),
            patch(
                "baloo.github.webhook_handler.verify_repo_belongs_to_installation",
                new=AsyncMock(return_value=False),
            ),
        ):
            from baloo.github.webhook_handler import _validate_webhook_security

            with pytest.raises(HTTPException) as exc_info:
                await _validate_webhook_security(111, "org/other-repo")

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_skips_repo_check_when_repo_is_none(self, monkeypatch):
        monkeypatch.setenv("INSTALLATION_ID", "")

        with patch(
            "baloo.github.auth.GitHubAuth.get_installation_token",
            return_value="tok",
        ):
            from baloo.github.webhook_handler import _validate_webhook_security

            result = await _validate_webhook_security(111, None)

        assert result is None


class TestHealthEndpoint:
    def test_health_returns_ok(self, monkeypatch):
        from fastapi.testclient import TestClient

        from baloo.github.webhook_handler import app

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
