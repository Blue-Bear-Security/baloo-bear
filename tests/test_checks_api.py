"""Tests for GitHub Checks API client."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from baloo.github.checks_api import GitHubChecksClient
from baloo.github.models import ReviewComment


@pytest.mark.asyncio
async def test_create_check_run():
    """Test creating a check run."""
    client = GitHubChecksClient(installation_id=123)

    with patch("baloo.github.checks_api.GitHubAuth") as mock_auth_class:
        # Mock authentication
        mock_auth = MagicMock()
        mock_auth.get_installation_token.return_value = "fake_token"
        mock_auth_class.return_value = mock_auth

        with patch("httpx.AsyncClient") as mock_client_class:
            # Setup mock response
            mock_response = AsyncMock()
            mock_response.json = MagicMock(return_value={"id": 12345})
            mock_response.raise_for_status = MagicMock()

            # Setup mock client context manager
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Reinitialize client to use mocked auth
            client = GitHubChecksClient(installation_id=123)

            # Call the method
            check_run_id = await client.create_check_run(
                repo_full_name="owner/repo",
                commit_sha="abc123def",
                name="Test Check",
                conclusion="neutral",
                summary="Test summary",
            )

            # Verify
            assert check_run_id == "12345"
            mock_client.post.assert_called_once()

            # Verify payload structure
            call_args = mock_client.post.call_args
            payload = call_args[1]["json"]
            assert payload["name"] == "Test Check"
            assert payload["head_sha"] == "abc123def"
            assert payload["status"] == "completed"
            assert payload["conclusion"] == "neutral"
            assert payload["output"]["summary"] == "Test summary"


@pytest.mark.asyncio
async def test_add_annotations_includes_category():
    """Test that annotations include category information."""
    findings = [
        ReviewComment(
            path="test.py",
            line=10,
            body="Security issue description",
            severity="MEDIUM",
            category="Security",
        ),
        ReviewComment(
            path="main.py", line=25, body="Bug description", severity="MEDIUM", category="Bugs"
        ),
    ]

    with patch("baloo.github.checks_api.GitHubAuth") as mock_auth_class:
        # Mock authentication
        mock_auth = MagicMock()
        mock_auth.get_installation_token.return_value = "fake_token"
        mock_auth_class.return_value = mock_auth

        with patch("httpx.AsyncClient") as mock_client_class:
            # Setup mock response
            mock_response = AsyncMock()
            mock_response.raise_for_status = MagicMock()

            # Setup mock client context manager
            mock_client = AsyncMock()
            mock_client.patch.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Initialize client with mocked auth
            client = GitHubChecksClient(installation_id=123)

            # Call the method
            await client.add_annotations(
                repo_full_name="owner/repo", check_run_id="12345", findings=findings
            )

            # Verify
            mock_client.patch.assert_called_once()

            # Verify annotations include category
            call_args = mock_client.patch.call_args
            annotations = call_args[1]["json"]["output"]["annotations"]

            assert len(annotations) == 2

            # Check first annotation
            assert annotations[0]["path"] == "test.py"
            assert annotations[0]["start_line"] == 10
            assert annotations[0]["annotation_level"] == "warning"
            assert annotations[0]["message"].startswith("Security:")
            assert annotations[0]["title"] == "[MEDIUM] Security"

            # Check second annotation
            assert annotations[1]["path"] == "main.py"
            assert annotations[1]["start_line"] == 25
            assert annotations[1]["message"].startswith("Bugs:")
            assert annotations[1]["title"] == "[MEDIUM] Bugs"


@pytest.mark.asyncio
async def test_add_annotations_empty_list():
    """Test adding annotations with empty findings list."""
    with patch("baloo.github.checks_api.GitHubAuth") as mock_auth_class:
        # Mock authentication
        mock_auth = MagicMock()
        mock_auth.get_installation_token.return_value = "fake_token"
        mock_auth_class.return_value = mock_auth

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Initialize client with mocked auth
            client = GitHubChecksClient(installation_id=123)

            # Call with empty list
            await client.add_annotations(
                repo_full_name="owner/repo", check_run_id="12345", findings=[]
            )

            # Should not make any API calls
            mock_client.patch.assert_not_called()


@pytest.mark.asyncio
async def test_add_annotations_truncates_to_50():
    """Test that annotations are limited to 50 per GitHub API requirements."""
    # Create 100 findings
    findings = [
        ReviewComment(
            path=f"file{i}.py", line=i, body=f"Issue {i}", severity="MEDIUM", category="Quality"
        )
        for i in range(100)
    ]

    with patch("baloo.github.checks_api.GitHubAuth") as mock_auth_class:
        # Mock authentication
        mock_auth = MagicMock()
        mock_auth.get_installation_token.return_value = "fake_token"
        mock_auth_class.return_value = mock_auth

        with patch("httpx.AsyncClient") as mock_client_class:
            # Setup mock response
            mock_response = AsyncMock()
            mock_response.raise_for_status = MagicMock()

            # Setup mock client
            mock_client = AsyncMock()
            mock_client.patch.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Initialize client with mocked auth
            client = GitHubChecksClient(installation_id=123)

            # Call the method
            await client.add_annotations(
                repo_full_name="owner/repo", check_run_id="12345", findings=findings
            )

            # Verify only 50 annotations were sent
            call_args = mock_client.patch.call_args
            annotations = call_args[1]["json"]["output"]["annotations"]
            assert len(annotations) == 50


@pytest.mark.asyncio
async def test_create_check_run_with_different_conclusions():
    """Test creating check runs with different conclusion values."""
    for conclusion in ["success", "failure", "neutral", "cancelled"]:
        with patch("baloo.github.checks_api.GitHubAuth") as mock_auth_class:
            # Mock authentication
            mock_auth = MagicMock()
            mock_auth.get_installation_token.return_value = "fake_token"
            mock_auth_class.return_value = mock_auth

            with patch("httpx.AsyncClient") as mock_client_class:
                # Setup mock
                mock_response = AsyncMock()
                mock_response.json = MagicMock(return_value={"id": 99999})
                mock_response.raise_for_status = MagicMock()

                mock_client = AsyncMock()
                mock_client.post.return_value = mock_response
                mock_client_class.return_value.__aenter__.return_value = mock_client

                # Initialize client with mocked auth
                client = GitHubChecksClient(installation_id=123)

                # Call with specific conclusion
                await client.create_check_run(
                    repo_full_name="owner/repo",
                    commit_sha="abc123",
                    name="Test",
                    conclusion=conclusion,
                    summary="Test",
                )

                # Verify conclusion was set correctly
                call_args = mock_client.post.call_args
                payload = call_args[1]["json"]
                assert payload["conclusion"] == conclusion
