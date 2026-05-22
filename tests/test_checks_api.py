"""Tests for GitHub Checks API client."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from baloo.github.checks_api import GitHubChecksClient
from baloo.github.models import ReviewComment


def _mock_response(body: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = body or {}
    return resp


def _make_client() -> tuple[GitHubChecksClient, AsyncMock]:
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    auth = MagicMock()
    auth.get_installation_token.return_value = "fake_token"
    client = GitHubChecksClient(installation_id=123, http_client=mock_http, auth=auth)
    return client, mock_http


@pytest.mark.asyncio
async def test_create_check_run():
    client, mock_http = _make_client()
    mock_http.post.return_value = _mock_response({"id": 12345})

    check_run_id = await client.create_check_run(
        repo_full_name="owner/repo",
        commit_sha="abc123def",
        name="Test Check",
        conclusion="neutral",
        summary="Test summary",
    )

    assert check_run_id == "12345"
    mock_http.post.assert_called_once()
    payload = mock_http.post.call_args[1]["json"]
    assert payload["name"] == "Test Check"
    assert payload["head_sha"] == "abc123def"
    assert payload["status"] == "completed"
    assert payload["conclusion"] == "neutral"
    assert payload["output"]["summary"] == "Test summary"


@pytest.mark.asyncio
async def test_add_annotations_includes_category():
    findings = [
        ReviewComment(
            path="test.py", line=10, body="Security issue", severity="MEDIUM", category="Security"
        ),
        ReviewComment(path="main.py", line=25, body="Bug desc", severity="MEDIUM", category="Bugs"),
    ]
    client, mock_http = _make_client()
    mock_http.patch.return_value = _mock_response()

    await client.add_annotations(
        repo_full_name="owner/repo", check_run_id="12345", findings=findings
    )

    mock_http.patch.assert_called_once()
    annotations = mock_http.patch.call_args[1]["json"]["output"]["annotations"]
    assert len(annotations) == 2
    assert annotations[0]["path"] == "test.py"
    assert annotations[0]["start_line"] == 10
    assert annotations[0]["annotation_level"] == "warning"
    assert annotations[0]["message"].startswith("Security:")
    assert annotations[0]["title"] == "[MEDIUM] Security"
    assert annotations[1]["path"] == "main.py"
    assert annotations[1]["message"].startswith("Bugs:")


@pytest.mark.asyncio
async def test_add_annotations_empty_list():
    client, mock_http = _make_client()

    await client.add_annotations(repo_full_name="owner/repo", check_run_id="12345", findings=[])

    mock_http.patch.assert_not_called()


@pytest.mark.asyncio
async def test_add_annotations_truncates_to_50():
    findings = [
        ReviewComment(
            path=f"file{i}.py",
            line=i,
            body=f"Issue {i}",
            severity="MEDIUM",
            category="Quality",
        )
        for i in range(100)
    ]
    client, mock_http = _make_client()
    mock_http.patch.return_value = _mock_response()

    await client.add_annotations(
        repo_full_name="owner/repo", check_run_id="12345", findings=findings
    )

    annotations = mock_http.patch.call_args[1]["json"]["output"]["annotations"]
    assert len(annotations) == 50


@pytest.mark.asyncio
async def test_create_check_run_with_different_conclusions():
    for conclusion in ["success", "failure", "neutral", "cancelled"]:
        client, mock_http = _make_client()
        mock_http.post.return_value = _mock_response({"id": 99999})

        await client.create_check_run(
            repo_full_name="owner/repo",
            commit_sha="abc123",
            name="Test",
            conclusion=conclusion,
            summary="Test",
        )

        payload = mock_http.post.call_args[1]["json"]
        assert payload["conclusion"] == conclusion
