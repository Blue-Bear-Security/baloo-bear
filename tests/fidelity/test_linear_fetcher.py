"""Tests for the Linear issue fetcher."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from baloo.fidelity.linear_fetcher import fetch_linear_issue_content


class _MockResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(
            {
                "data": {
                    "issue": {
                        "identifier": "PER-603",
                        "title": "Add endpoint boundary recording",
                        "description": "## Goal\n\nRecord the trust posture.",
                        "url": "https://linear.app/example/issue/PER-603",
                        "team": {"key": "PER", "name": "Perihelion"},
                        "state": {"name": "In Progress"},
                        "comments": {"nodes": []},
                    }
                }
            }
        ).encode()


@pytest.mark.asyncio
async def test_returns_none_when_no_api_key():
    with patch("baloo.fidelity.linear_fetcher.settings") as mock_settings:
        mock_settings.linear_api_key = ""
        result = await fetch_linear_issue_content("PER-603")
    assert result is None


@pytest.mark.asyncio
async def test_formats_issue_as_plan_content():
    with (
        patch("baloo.fidelity.linear_fetcher.settings") as mock_settings,
        patch("baloo.fidelity.linear_fetcher.request.urlopen", return_value=_MockResponse()),
    ):
        mock_settings.linear_api_key = "lin_api_test"
        mock_settings.linear_api_url = "https://api.linear.app/graphql"
        result = await fetch_linear_issue_content("PER-603")

    assert result is not None
    assert "# Linear Issue PER-603: Add endpoint boundary recording" in result
    assert "Record the trust posture" in result
    assert "https://linear.app/example/issue/PER-603" in result


@pytest.mark.asyncio
async def test_returns_none_on_http_error():
    from urllib import error as url_error

    with (
        patch("baloo.fidelity.linear_fetcher.settings") as mock_settings,
        patch(
            "baloo.fidelity.linear_fetcher.request.urlopen",
            side_effect=url_error.HTTPError(None, 401, "Unauthorized", {}, None),
        ),
    ):
        mock_settings.linear_api_key = "lin_api_test"
        mock_settings.linear_api_url = "https://api.linear.app/graphql"
        result = await fetch_linear_issue_content("PER-603")

    assert result is None


@pytest.mark.asyncio
async def test_returns_none_on_connection_reset():
    with (
        patch("baloo.fidelity.linear_fetcher.settings") as mock_settings,
        patch(
            "baloo.fidelity.linear_fetcher.request.urlopen",
            side_effect=ConnectionResetError("connection reset"),
        ),
    ):
        mock_settings.linear_api_key = "lin_api_test"
        mock_settings.linear_api_url = "https://api.linear.app/graphql"
        result = await fetch_linear_issue_content("PER-603")

    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_issue_not_found():
    class _EmptyResponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"data": {"issue": None}}).encode()

    with (
        patch("baloo.fidelity.linear_fetcher.settings") as mock_settings,
        patch("baloo.fidelity.linear_fetcher.request.urlopen", return_value=_EmptyResponse()),
    ):
        mock_settings.linear_api_key = "lin_api_test"
        mock_settings.linear_api_url = "https://api.linear.app/graphql"
        result = await fetch_linear_issue_content("MISSING-1")

    assert result is None


@pytest.mark.asyncio
async def test_linear_content_used_as_fidelity_fallback_when_no_plan_file():
    """_run_fidelity_analysis uses linear_fallback when no plan file is found."""
    from unittest.mock import AsyncMock, MagicMock

    from baloo.github.models import FileChange, PRContext, PRDiscussionContext, PRMetadata
    from baloo.review.orchestrator import _run_fidelity_analysis

    pr_context = PRContext(
        metadata=PRMetadata(
            repo_full_name="org/repo",
            pr_number=1,
            title="feat: PER-42 add login",
            description="",
            author="dev",
            base_branch="main",
            head_branch="feat/PER-42-login",
            head_sha="abc",
            files_changed=[
                FileChange(
                    filename="auth.py",
                    status="modified",
                    additions=1,
                    deletions=0,
                    changes=1,
                )
            ],
        ),
        discussion=PRDiscussionContext(),
        diff="diff",
    )

    mock_client = MagicMock()
    linear_content = "# Linear Issue PER-42\n\n## Description\n\nAdd login flow."

    with (
        patch("baloo.review.orchestrator.extract_ticket_id", return_value="PER-42"),
        patch("baloo.review.orchestrator.fetch_plan_content", new=AsyncMock(return_value=None)),
        patch(
            "baloo.review.orchestrator.analyze_fidelity",
            new=AsyncMock(
                return_value=MagicMock(
                    fidelity_score=85,
                    ticket_id="PER-42",
                    logic_summary="Matches plan",
                    requirements=[],
                    extras=[],
                    discrepancies=[],
                    metadata={},
                )
            ),
        ),
    ):
        report, result = await _run_fidelity_analysis(
            mock_client, "org/repo", pr_context, linear_fallback=linear_content
        )

    assert result is not None
