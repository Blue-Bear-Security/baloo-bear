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
                        "description": (
                            "## Goal\n\nRecord the trust posture at every service boundary.\n\n"
                            "## Requirements\n\n- Log every boundary crossing with timestamp\n"
                            "- Store events in the audit trail database\n"
                            "- Alert on anomalies within 60 seconds\n"
                            "- Retain logs for 90 days\n"
                            "- Export to SIEM via syslog\n\n"
                            "## Acceptance Criteria\n\n"
                            "- All ingress and egress events are captured\n"
                            "- Retention policy enforced automatically"
                        ),
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
    from baloo.fidelity.linear_fetcher import LinearFetchResult

    with patch("baloo.fidelity.linear_fetcher.settings") as mock_settings:
        mock_settings.linear_api_key = ""
        result = await fetch_linear_issue_content("PER-603")
    assert isinstance(result, LinearFetchResult)
    assert result.content is None


@pytest.mark.asyncio
async def test_formats_issue_as_plan_content():
    with (
        patch("baloo.fidelity.linear_fetcher.settings") as mock_settings,
        patch("baloo.fidelity.linear_fetcher.request.urlopen", return_value=_MockResponse()),
    ):
        mock_settings.linear_api_key = "lin_api_test"
        mock_settings.linear_api_url = "https://api.linear.app/graphql"
        result = await fetch_linear_issue_content("PER-603")

    assert result.content is not None
    assert "# Linear Issue PER-603: Add endpoint boundary recording" in result.content
    assert "Record the trust posture" in result.content
    assert "https://linear.app/example/issue/PER-603" in result.content


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

    assert result.content is None


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

    assert result.content is None


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

    assert result.content is None


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


@pytest.mark.asyncio
async def test_linear_content_supplements_existing_plan_file():
    """When both a plan file and Linear content exist, both are combined."""
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
    plan_file_content = "# Plan\n\nDetailed design doc."
    linear_content = "# Linear Issue PER-42\n\n## Description\n\nAdd login flow."

    captured = {}

    async def capture_analyze_fidelity(plan_content, **kwargs):
        captured["plan_content"] = plan_content
        return MagicMock(
            fidelity_score=90,
            ticket_id="PER-42",
            logic_summary="Matches",
            requirements=[],
            extras=[],
            discrepancies=[],
            metadata={},
        )

    with (
        patch("baloo.review.orchestrator.extract_ticket_id", return_value="PER-42"),
        patch(
            "baloo.review.orchestrator.fetch_plan_content",
            new=AsyncMock(return_value=plan_file_content),
        ),
        patch(
            "baloo.review.orchestrator.analyze_fidelity",
            new=AsyncMock(side_effect=capture_analyze_fidelity),
        ),
    ):
        report, result = await _run_fidelity_analysis(
            mock_client, "org/repo", pr_context, linear_fallback=linear_content
        )

    assert result is not None
    assert "Detailed design doc" in captured["plan_content"]
    assert "Add login flow" in captured["plan_content"]


class TestLinearFetchResult:
    def test_returns_fetch_result_type_on_success(self):
        from baloo.fidelity.linear_fetcher import LinearFetchResult

        result = LinearFetchResult(content="# Issue\n\nSome content.", skipped_reason=None)
        assert result.content is not None
        assert result.skipped_reason is None

    def test_returns_fetch_result_type_on_insufficient_detail(self):
        from baloo.fidelity.linear_fetcher import LinearFetchResult

        result = LinearFetchResult(content=None, skipped_reason="insufficient_detail")
        assert result.content is None
        assert result.skipped_reason == "insufficient_detail"


class TestTicketSufficiency:
    def test_sufficient_ticket_passes_threshold(self):
        from baloo.fidelity.linear_fetcher import _is_ticket_sufficient

        issue = {
            "title": "Add SSO login endpoint",
            "description": (
                "## Goal\n\nImplement OAuth2 login flow.\n\n"
                "## Requirements\n\n- Support Google and GitHub providers\n"
                "- Return JWT token on success\n- Rate limit to 10 req/min\n\n"
                "## Acceptance Criteria\n\n"
                "- Users can log in with Google or GitHub OAuth2 credentials\n"
                "- A signed JWT token is returned on successful authentication\n"
                "- Failed attempts are rate limited to 10 requests per minute\n"
                "- Token expiry is set to 1 hour with refresh token support"
            ),
        }
        assert _is_ticket_sufficient(issue) is True

    def test_one_liner_ticket_fails_threshold(self):
        from baloo.fidelity.linear_fetcher import _is_ticket_sufficient

        issue = {"title": "fix login bug", "description": ""}
        assert _is_ticket_sufficient(issue) is False

    def test_short_description_under_300_chars_fails(self):
        from baloo.fidelity.linear_fetcher import _is_ticket_sufficient

        issue = {"title": "Add feature", "description": "Do the thing."}
        assert _is_ticket_sufficient(issue) is False

    def test_missing_description_fails(self):
        from baloo.fidelity.linear_fetcher import _is_ticket_sufficient

        issue = {"title": "Add feature", "description": None}
        assert _is_ticket_sufficient(issue) is False


@pytest.mark.asyncio
async def test_fetch_returns_linear_fetch_result_on_success():
    from baloo.fidelity.linear_fetcher import LinearFetchResult

    with (
        patch("baloo.fidelity.linear_fetcher.settings") as mock_settings,
        patch("baloo.fidelity.linear_fetcher.request.urlopen", return_value=_MockResponse()),
    ):
        mock_settings.linear_api_key = "lin_api_test"
        mock_settings.linear_api_url = "https://api.linear.app/graphql"
        result = await fetch_linear_issue_content("PER-603")

    assert isinstance(result, LinearFetchResult)
    assert result.content is not None
    assert result.skipped_reason is None


@pytest.mark.asyncio
async def test_fetch_returns_none_content_when_no_api_key():
    from baloo.fidelity.linear_fetcher import LinearFetchResult

    with patch("baloo.fidelity.linear_fetcher.settings") as mock_settings:
        mock_settings.linear_api_key = ""
        result = await fetch_linear_issue_content("PER-603")

    assert isinstance(result, LinearFetchResult)
    assert result.content is None
    assert result.skipped_reason is None


@pytest.mark.asyncio
async def test_fetch_returns_insufficient_detail_for_stub_ticket():
    from baloo.fidelity.linear_fetcher import LinearFetchResult

    class _StubResponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(
                {
                    "data": {
                        "issue": {
                            "identifier": "PER-1",
                            "title": "fix bug",
                            "description": "",
                            "url": "",
                            "team": None,
                            "state": None,
                            "comments": {"nodes": []},
                        }
                    }
                }
            ).encode()

    with (
        patch("baloo.fidelity.linear_fetcher.settings") as mock_settings,
        patch("baloo.fidelity.linear_fetcher.request.urlopen", return_value=_StubResponse()),
    ):
        mock_settings.linear_api_key = "lin_api_test"
        mock_settings.linear_api_url = "https://api.linear.app/graphql"
        result = await fetch_linear_issue_content("PER-1")

    assert isinstance(result, LinearFetchResult)
    assert result.content is None
    assert result.skipped_reason == "insufficient_detail"
