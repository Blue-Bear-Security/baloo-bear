"""Tests for merge commit detection logic."""

from unittest.mock import AsyncMock, patch

import pytest

from baloo.github.api_client import GitHubAPIClient


class TestMergeCommitDetection:
    """Tests for is_merge_or_sync_commit method."""

    @pytest.fixture
    def github_client(self):
        """Create a GitHubAPIClient with mocked auth."""
        with patch("baloo.github.api_client.GitHubAuth"):
            return GitHubAPIClient(installation_id=123)

    @pytest.mark.asyncio
    async def test_detects_sync_when_parent_is_ancestor_of_base(self, github_client):
        """Should skip review when a merge commit parent is on the base branch."""
        commit_info = {
            "parents": [{"sha": "feature111"}, {"sha": "base000"}],
            "commit": {"message": "Merge branch 'main' into feature-branch"},
        }

        with (
            patch.object(github_client, "get_commit_info", new=AsyncMock(return_value=commit_info)),
            patch.object(
                github_client,
                "_commit_is_ancestor_of_branch",
                new=AsyncMock(side_effect=lambda repo, sha, branch: sha == "base000"),
            ),
        ):
            is_merge, reason = await github_client.is_merge_or_sync_commit(
                "owner/repo", "head123", "main"
            )

        assert is_merge is True
        assert "main" in reason
        assert "base000" in reason

    @pytest.mark.asyncio
    async def test_detects_sync_regardless_of_file_count(self, github_client):
        """File count is irrelevant — a large upstream sync should still be skipped."""
        commit_info = {
            "parents": [{"sha": "feature111"}, {"sha": "base000"}],
            "commit": {"message": "Synced with main"},  # non-standard message
        }

        with (
            patch.object(github_client, "get_commit_info", new=AsyncMock(return_value=commit_info)),
            patch.object(
                github_client,
                "_commit_is_ancestor_of_branch",
                new=AsyncMock(side_effect=lambda repo, sha, branch: sha == "base000"),
            ),
        ):
            is_merge, reason = await github_client.is_merge_or_sync_commit(
                "owner/repo", "head123", "main"
            )

        assert is_merge is True

    @pytest.mark.asyncio
    async def test_does_not_detect_regular_commit(self, github_client):
        """Single-parent commit is never a sync merge."""
        commit_info = {
            "parents": [{"sha": "abc123"}],
            "commit": {"message": "feat: add new feature"},
        }

        with patch.object(
            github_client, "get_commit_info", new=AsyncMock(return_value=commit_info)
        ):
            is_merge, reason = await github_client.is_merge_or_sync_commit(
                "owner/repo", "abc123", "main"
            )

        assert is_merge is False
        assert reason == ""

    @pytest.mark.asyncio
    async def test_does_not_detect_merge_between_feature_branches(self, github_client):
        """Merging one feature branch into another should not be skipped."""
        commit_info = {
            "parents": [{"sha": "feature-a"}, {"sha": "feature-b"}],
            "commit": {"message": "Merge branch 'feature-a' into feature-b"},
        }

        with (
            patch.object(github_client, "get_commit_info", new=AsyncMock(return_value=commit_info)),
            patch.object(
                github_client,
                "_commit_is_ancestor_of_branch",
                # Neither parent is on main
                new=AsyncMock(return_value=False),
            ),
        ):
            is_merge, reason = await github_client.is_merge_or_sync_commit(
                "owner/repo", "head123", "main"
            )

        assert is_merge is False
        assert reason == ""

    @pytest.mark.asyncio
    async def test_handles_api_error_gracefully(self, github_client):
        """Should return False if the commit info API call fails."""
        with patch.object(
            github_client,
            "get_commit_info",
            new=AsyncMock(side_effect=Exception("API error")),
        ):
            is_merge, reason = await github_client.is_merge_or_sync_commit(
                "owner/repo", "abc123", "main"
            )

        assert is_merge is False
        assert reason == ""

    @pytest.mark.asyncio
    async def test_handles_ancestor_check_error_gracefully(self, github_client):
        """Should return False if the ancestry compare API call fails."""
        commit_info = {
            "parents": [{"sha": "feature111"}, {"sha": "base000"}],
            "commit": {"message": "Merge branch 'main'"},
        }

        with (
            patch.object(github_client, "get_commit_info", new=AsyncMock(return_value=commit_info)),
            patch.object(
                github_client,
                "_commit_is_ancestor_of_branch",
                new=AsyncMock(side_effect=Exception("compare API error")),
            ),
        ):
            is_merge, reason = await github_client.is_merge_or_sync_commit(
                "owner/repo", "head123", "main"
            )

        assert is_merge is False
        assert reason == ""
