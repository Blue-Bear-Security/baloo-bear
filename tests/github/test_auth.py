"""Tests for GitHub webhook signature verification and pre-verified mode (DEN-1663)."""

import hashlib
import hmac
import importlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def webhook_secret():
    return "test-webhook-secret"


@pytest.fixture
def payload():
    return b'{"action": "opened", "pull_request": {"number": 1}}'


@pytest.fixture
def valid_signature(webhook_secret, payload):
    """Generate a valid HMAC-SHA256 signature for the test payload."""
    sig = hmac.new(
        webhook_secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={sig}"


@pytest.fixture(autouse=True)
def reset_settings_fixture():
    """Reset settings before and after each test to pick up env var changes."""
    from baloo.config import settings as settings_module

    settings_module.reset_settings()
    yield
    settings_module.reset_settings()


def _verify(payload: bytes, signature: str) -> bool:
    """Re-import auth module to pick up fresh settings."""
    import baloo.github.auth as auth_module

    importlib.reload(auth_module)
    return auth_module.verify_webhook_signature(payload, signature)


class TestVerifyWebhookSignature:
    """Tests for verify_webhook_signature with normal signature validation."""

    def test_valid_signature(self, monkeypatch, payload, valid_signature, webhook_secret):
        """Valid signature returns True."""
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", webhook_secret)
        monkeypatch.setenv("WEBHOOK_PRE_VERIFIED", "false")

        assert _verify(payload, valid_signature) is True

    def test_invalid_signature(self, monkeypatch, payload, webhook_secret):
        """Invalid signature returns False."""
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", webhook_secret)
        monkeypatch.setenv("WEBHOOK_PRE_VERIFIED", "false")

        assert _verify(payload, "sha256=invalid") is False

    def test_missing_signature_header(self, monkeypatch, payload, webhook_secret):
        """Missing signature header returns False."""
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", webhook_secret)
        monkeypatch.setenv("WEBHOOK_PRE_VERIFIED", "false")

        assert _verify(payload, "") is False

    def test_wrong_algorithm(self, monkeypatch, payload, webhook_secret):
        """Non-sha256 algorithm returns False."""
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", webhook_secret)
        monkeypatch.setenv("WEBHOOK_PRE_VERIFIED", "false")

        assert _verify(payload, "sha1=abc123") is False


class TestWebhookPreVerified:
    """Tests for WEBHOOK_PRE_VERIFIED mode (DEN-1663)."""

    def test_pre_verified_skips_signature_check(self, monkeypatch, payload):
        """When WEBHOOK_PRE_VERIFIED=true, returns True without checking signature."""
        monkeypatch.setenv("WEBHOOK_PRE_VERIFIED", "true")

        assert _verify(payload, "") is True

    def test_pre_verified_with_invalid_signature(self, monkeypatch, payload):
        """When WEBHOOK_PRE_VERIFIED=true, invalid signature still returns True."""
        monkeypatch.setenv("WEBHOOK_PRE_VERIFIED", "true")

        assert _verify(payload, "sha256=tampered") is True

    def test_pre_verified_default_is_false(self, monkeypatch, payload, webhook_secret):
        """Default WEBHOOK_PRE_VERIFIED is False — signature check is active."""
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", webhook_secret)
        monkeypatch.delenv("WEBHOOK_PRE_VERIFIED", raising=False)

        assert _verify(payload, "sha256=invalid") is False


class TestVerifyRepoBelongsToInstallation:
    """Tests for verify_repo_belongs_to_installation."""

    @pytest.mark.asyncio
    async def test_returns_true_when_repo_accessible(self, monkeypatch):
        mock_response = MagicMock()
        mock_response.status_code = 200

        monkeypatch.setattr(
            "baloo.github.auth.GitHubAuth.get_installation_token",
            lambda self, iid: "tok",
        )

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            from baloo.github.auth import verify_repo_belongs_to_installation

            result = await verify_repo_belongs_to_installation(111, "org/repo")

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_repo_not_found(self, monkeypatch):
        mock_response = MagicMock()
        mock_response.status_code = 404

        monkeypatch.setattr(
            "baloo.github.auth.GitHubAuth.get_installation_token",
            lambda self, iid: "tok",
        )

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            from baloo.github.auth import verify_repo_belongs_to_installation

            result = await verify_repo_belongs_to_installation(111, "org/other-repo")

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_token_fetch_fails(self, monkeypatch):
        import httpx

        def raise_http_error(self, iid):
            raise httpx.HTTPStatusError("404", request=MagicMock(), response=MagicMock())

        monkeypatch.setattr("baloo.github.auth.GitHubAuth.get_installation_token", raise_http_error)

        from baloo.github.auth import verify_repo_belongs_to_installation

        result = await verify_repo_belongs_to_installation(999, "org/repo")

        assert result is False


class TestGenerateJwt:
    def test_generate_jwt_returns_string(self, monkeypatch):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ).decode()

        monkeypatch.setenv("GITHUB_APP_ID", "12345")
        monkeypatch.setenv("GITHUB_PRIVATE_KEY", pem)

        import importlib

        import baloo.github.auth as auth_module

        importlib.reload(auth_module)

        token = auth_module.generate_jwt()
        assert isinstance(token, str)
        assert len(token) > 0
        assert token.count(".") == 2


class TestVerifyWebhookSignatureMalformed:
    def test_malformed_signature_no_equals_returns_false(
        self, monkeypatch, payload, webhook_secret
    ):
        """Signature with no '=' raises ValueError in split — caught, returns False."""
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", webhook_secret)
        monkeypatch.setenv("WEBHOOK_PRE_VERIFIED", "false")

        assert _verify(payload, "sha256noequalssign") is False


class TestGetInstallationToken:
    def test_cache_hit_returns_cached_token_without_http(self, monkeypatch):
        """When a cached token with >5min remaining exists, no HTTP call is made."""
        from datetime import datetime, timedelta, timezone
        from unittest.mock import patch

        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ).decode()
        monkeypatch.setenv("GITHUB_APP_ID", "12345")
        monkeypatch.setenv("GITHUB_PRIVATE_KEY", pem)

        import importlib

        import baloo.github.auth as auth_module

        importlib.reload(auth_module)

        auth = auth_module.GitHubAuth()
        future_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
        auth._installation_tokens[42] = ("cached_token", future_expiry)

        with patch("httpx.post") as mock_post:
            token = auth.get_installation_token(42)

        assert token == "cached_token"
        mock_post.assert_not_called()

    def test_cache_miss_fetches_new_token(self, monkeypatch):
        """When no cached token exists, fetches from GitHub API and caches result."""
        from datetime import datetime, timedelta, timezone
        from unittest.mock import MagicMock, patch

        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ).decode()
        monkeypatch.setenv("GITHUB_APP_ID", "12345")
        monkeypatch.setenv("GITHUB_PRIVATE_KEY", pem)

        import importlib

        import baloo.github.auth as auth_module

        importlib.reload(auth_module)

        future_expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "token": "fresh_token",
            "expires_at": future_expiry,
        }
        mock_response.raise_for_status = MagicMock()

        auth = auth_module.GitHubAuth()
        with patch("httpx.post", return_value=mock_response) as mock_post:
            token = auth.get_installation_token(99)

        assert token == "fresh_token"
        mock_post.assert_called_once()
        assert 99 in auth._installation_tokens


class TestVerifyRepoBelongsToInstallationReloaded:
    @pytest.mark.asyncio
    async def test_returns_false_on_404(self, monkeypatch):
        """Returns False when the repo is not accessible (404) — uses reloaded module."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ).decode()
        monkeypatch.setenv("GITHUB_APP_ID", "12345")
        monkeypatch.setenv("GITHUB_PRIVATE_KEY", pem)

        import importlib

        import baloo.github.auth as auth_module

        importlib.reload(auth_module)

        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_async_client = AsyncMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=False)
        mock_async_client.get = AsyncMock(return_value=mock_response)

        with (
            patch.object(auth_module.GitHubAuth, "get_installation_token", return_value="tok"),
            patch("httpx.AsyncClient", return_value=mock_async_client),
        ):
            result = await auth_module.verify_repo_belongs_to_installation(42, "org/private-repo")

        assert result is False
