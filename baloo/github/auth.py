"""GitHub App authentication utilities."""

import hashlib
import hmac
import logging
import time
from datetime import datetime, timedelta, timezone

import jwt

from baloo.config.settings import settings

logger = logging.getLogger(__name__)


def generate_jwt() -> str:
    """
    Generate a JWT for GitHub App authentication.

    Returns:
        JWT token as string
    """
    now = int(time.time())
    payload = {
        "iat": now - 60,  # Issued at time (60 seconds in the past to allow for clock drift)
        "exp": now + (10 * 60),  # JWT expiration time (10 minutes)
        "iss": settings.github_app_id,
    }

    token = jwt.encode(payload, settings.github_private_key_bytes, algorithm="RS256")
    return token


def verify_webhook_signature(payload_body: bytes, signature_header: str) -> bool:
    """
    Verify that the webhook payload was sent from GitHub by validating its signature.

    When WEBHOOK_PRE_VERIFIED is True, the signature check is skipped because
    a trusted proxy (e.g., baloo-cloud) has already validated it.

    Args:
        payload_body: Raw request body bytes
        signature_header: X-Hub-Signature-256 header value

    Returns:
        True if signature is valid, False otherwise
    """
    if settings.webhook_pre_verified:
        logger.debug("Webhook signature check skipped — WEBHOOK_PRE_VERIFIED is enabled")
        return True

    if not signature_header:
        return False

    # GitHub sends the signature as "sha256=<signature>"
    try:
        hash_algorithm, signature = signature_header.split("=")
    except ValueError:
        return False

    if hash_algorithm != "sha256":
        return False

    # Calculate expected signature
    expected_signature = hmac.new(
        settings.github_webhook_secret.encode("utf-8"),
        payload_body,
        hashlib.sha256,
    ).hexdigest()

    # Compare signatures using constant-time comparison
    return hmac.compare_digest(expected_signature, signature)


class GitHubAuth:
    """Manages GitHub App authentication and installation tokens."""

    def __init__(self):
        self._installation_tokens: dict[int, tuple[str, datetime]] = {}

    def get_installation_token(self, installation_id: int) -> str:
        """
        Get an installation access token for the given installation ID.

        Installation tokens are cached and reused until they expire.

        Args:
            installation_id: GitHub App installation ID

        Returns:
            Installation access token
        """
        # Check if we have a cached token that's still valid
        if installation_id in self._installation_tokens:
            token, expires_at = self._installation_tokens[installation_id]
            # Use token if it doesn't expire within the next 5 minutes
            if datetime.now(timezone.utc) + timedelta(minutes=5) < expires_at:
                return token

        # Need to fetch a new token
        import httpx

        jwt_token = generate_jwt()
        url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"

        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        response = httpx.post(url, headers=headers)
        response.raise_for_status()

        data = response.json()
        token = data["token"]
        expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))

        # Cache the token
        self._installation_tokens[installation_id] = (token, expires_at)

        return token
