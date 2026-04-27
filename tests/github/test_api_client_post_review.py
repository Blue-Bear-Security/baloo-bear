"""Tests for posting pull request reviews."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from baloo.github.api_client import GitHubAPIClient
from baloo.github.models import ReviewComment, ReviewResult


def _mock_response(body: dict | None = None):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = body or {}
    return resp


@pytest.mark.asyncio
async def test_post_review_reports_and_logs_dropped_invalid_diff_comments(caplog):
    """Invalid diff-line findings should be observable internally."""
    diff = "\n".join(
        [
            "diff --git a/file.py b/file.py",
            "@@ -8,3 +8,3 @@",
            " context",
            "+added",
            " context",
        ]
    )
    valid = ReviewComment(
        path="file.py",
        line=9,
        body="Valid high finding",
        severity="HIGH",
        category="Bugs",
    )
    invalid = ReviewComment(
        path="file.py",
        line=99,
        body="Invalid high finding",
        severity="HIGH",
        category="Silent Failures",
    )

    with (
        patch("httpx.AsyncClient") as mock_client_cls,
        patch(
            "baloo.github.auth.GitHubAuth.get_installation_token",
            return_value="fake-token",
        ),
    ):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=_mock_response({"id": 123}))
        mock_client_cls.return_value = mock_client

        client = GitHubAPIClient(installation_id=1)
        with caplog.at_level("WARNING", logger="baloo.github.api_client"):
            result = await client.post_review(
                "owner/repo",
                42,
                ReviewResult(summary="Review summary", comments=[valid, invalid]),
                diff=diff,
            )

    assert result.attempted == 2
    assert result.posted == 1
    assert len(result.dropped) == 1
    assert result.dropped[0].comment == invalid
    assert result.dropped[0].reason == "line_not_in_diff"
    assert result.dropped[0].nearest_valid_line == 10
    assert "reason=line_not_in_diff" in caplog.text
    assert "severity=HIGH" in caplog.text
    assert "category=Silent Failures" in caplog.text
