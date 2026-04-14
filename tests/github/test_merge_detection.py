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
    async def test_detects_merge_commit_with_base_branch(self, github_client):
        """Should detect merge commit that merges base branch into feature."""
        commit_info = {
            "parents": [{"sha": "abc123"}, {"sha": "def456"}],
            "commit": {"message": "Merge branch 'dev' into feature-branch"},
            "files": [],
        }

        with patch.object(
            github_client, "get_commit_info", new=AsyncMock(return_value=commit_info)
        ):
            is_merge, reason = await github_client.is_merge_or_sync_commit(
                "owner/repo", "abc123", "dev"
            )

        assert is_merge is True
        assert "merge commit" in reason.lower()

    @pytest.mark.asyncio
    async def test_detects_merge_commit_with_conflict_resolution(self, github_client):
        """Should detect merge commit with small number of conflict resolution files."""
        commit_info = {
            "parents": [{"sha": "abc123"}, {"sha": "def456"}],
            "commit": {"message": "Merge branch 'main' into my-feature"},
            "files": [
                {"filename": "file1.py"},
                {"filename": "file2.py"},
            ],
        }

        with patch.object(
            github_client, "get_commit_info", new=AsyncMock(return_value=commit_info)
        ):
            is_merge, reason = await github_client.is_merge_or_sync_commit(
                "owner/repo", "abc123", "main"
            )

        assert is_merge is True
        assert "2 file(s)" in reason

    @pytest.mark.asyncio
    async def test_does_not_detect_regular_commit(self, github_client):
        """Should not detect regular (non-merge) commit."""
        commit_info = {
            "parents": [{"sha": "abc123"}],  # Only one parent = not a merge
            "commit": {"message": "feat: add new feature"},
            "files": [{"filename": "feature.py"}],
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
    async def test_does_not_detect_merge_with_many_files(self, github_client):
        """Should not detect merge commit with many file changes (likely real work)."""
        commit_info = {
            "parents": [{"sha": "abc123"}, {"sha": "def456"}],
            "commit": {"message": "Merge branch 'main' into feature"},
            "files": [{"filename": f"file{i}.py"} for i in range(10)],  # 10 files
        }

        with patch.object(
            github_client, "get_commit_info", new=AsyncMock(return_value=commit_info)
        ):
            is_merge, reason = await github_client.is_merge_or_sync_commit(
                "owner/repo", "abc123", "main"
            )

        assert is_merge is False

    @pytest.mark.asyncio
    async def test_does_not_detect_merge_with_unrelated_message(self, github_client):
        """Should not detect merge commit that doesn't match base branch pattern."""
        commit_info = {
            "parents": [{"sha": "abc123"}, {"sha": "def456"}],
            "commit": {"message": "Merge branch 'other-feature' into my-feature"},
            "files": [],
        }

        with patch.object(
            github_client, "get_commit_info", new=AsyncMock(return_value=commit_info)
        ):
            # Base branch is 'main', but merge is from 'other-feature'
            is_merge, reason = await github_client.is_merge_or_sync_commit(
                "owner/repo", "abc123", "main"
            )

        assert is_merge is False

    @pytest.mark.asyncio
    async def test_handles_api_error_gracefully(self, github_client):
        """Should return False if API call fails."""
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
    async def test_detects_pull_request_merge(self, github_client):
        """Should detect merge pull request commits."""
        commit_info = {
            "parents": [{"sha": "abc123"}, {"sha": "def456"}],
            "commit": {"message": "Merge pull request #123 from user/feature"},
            "files": [],
        }

        with patch.object(
            github_client, "get_commit_info", new=AsyncMock(return_value=commit_info)
        ):
            is_merge, reason = await github_client.is_merge_or_sync_commit(
                "owner/repo", "abc123", "main"
            )

        assert is_merge is True

    @pytest.mark.asyncio
    async def test_detects_remote_tracking_branch_merge(self, github_client):
        """Should detect merge from remote-tracking branch."""
        commit_info = {
            "parents": [{"sha": "abc123"}, {"sha": "def456"}],
            "commit": {
                "message": "Merge remote-tracking branch 'origin/main' into feature"
            },
            "files": [{"filename": "conflict.py"}],
        }

        with patch.object(
            github_client, "get_commit_info", new=AsyncMock(return_value=commit_info)
        ):
            is_merge, reason = await github_client.is_merge_or_sync_commit(
                "owner/repo", "abc123", "main"
            )

        assert is_merge is True
