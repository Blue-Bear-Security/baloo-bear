"""Tests for fetch_plan_content."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_github_client(
    *,
    get_file_content_side_effect=None,
    get_file_content_return=None,
    list_directory_return=None,
):
    client = MagicMock()
    if get_file_content_side_effect:
        client.get_file_content = AsyncMock(side_effect=get_file_content_side_effect)
    else:
        client.get_file_content = AsyncMock(return_value=get_file_content_return)
    client.list_directory = AsyncMock(return_value=list_directory_return or [])
    return client


class TestFetchPlanContent:
    @pytest.mark.asyncio
    async def test_exact_path_match_returns_content(self, monkeypatch):
        from baloo.fidelity.plan_fetcher import fetch_plan_content

        monkeypatch.setenv("FIDELITY_PLAN_PATH_PATTERN", "docs/plans/{ticket_id}.md")
        gc = _make_github_client(get_file_content_return="# Plan content")

        result = await fetch_plan_content(gc, "org/repo", "PROJ-123")

        assert result == "# Plan content"
        gc.get_file_content.assert_called_once_with("org/repo", "docs/plans/PROJ-123.md", None)

    @pytest.mark.asyncio
    async def test_exact_not_found_and_empty_dir_returns_none(self, monkeypatch):
        from baloo.fidelity.plan_fetcher import fetch_plan_content

        monkeypatch.setenv("FIDELITY_PLAN_PATH_PATTERN", "docs/plans/{ticket_id}.md")
        gc = _make_github_client(get_file_content_return=None, list_directory_return=[])

        result = await fetch_plan_content(gc, "org/repo", "PROJ-123")

        assert result is None

    @pytest.mark.asyncio
    async def test_exact_not_found_no_prefix_match_returns_none(self, monkeypatch):
        from baloo.fidelity.plan_fetcher import fetch_plan_content

        monkeypatch.setenv("FIDELITY_PLAN_PATH_PATTERN", "docs/plans/{ticket_id}.md")
        gc = _make_github_client(
            get_file_content_return=None,
            list_directory_return=["OTHER-456.md", "PROJ-999-other.md"],
        )

        result = await fetch_plan_content(gc, "org/repo", "PROJ-123")

        assert result is None

    @pytest.mark.asyncio
    async def test_prefix_match_found_returns_content(self, monkeypatch):
        from baloo.fidelity.plan_fetcher import fetch_plan_content

        monkeypatch.setenv("FIDELITY_PLAN_PATH_PATTERN", "docs/plans/{ticket_id}.md")

        call_count = 0

        async def _get_file(repo, path, ref):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None  # exact path miss
            return "# Prefix plan content"

        gc = MagicMock()
        gc.get_file_content = AsyncMock(side_effect=_get_file)
        gc.list_directory = AsyncMock(return_value=["PROJ-123-feature-name.md"])

        result = await fetch_plan_content(gc, "org/repo", "PROJ-123")

        assert result == "# Prefix plan content"

    @pytest.mark.asyncio
    async def test_prefix_match_but_content_none_returns_none(self, monkeypatch):
        from baloo.fidelity.plan_fetcher import fetch_plan_content

        monkeypatch.setenv("FIDELITY_PLAN_PATH_PATTERN", "docs/plans/{ticket_id}.md")

        async def _get_file(repo, path, ref):
            return None

        gc = MagicMock()
        gc.get_file_content = AsyncMock(side_effect=_get_file)
        gc.list_directory = AsyncMock(return_value=["PROJ-123-something.md"])

        result = await fetch_plan_content(gc, "org/repo", "PROJ-123")

        assert result is None

    @pytest.mark.asyncio
    async def test_exception_returns_none(self, monkeypatch):
        from baloo.fidelity.plan_fetcher import fetch_plan_content

        monkeypatch.setenv("FIDELITY_PLAN_PATH_PATTERN", "docs/plans/{ticket_id}.md")
        gc = _make_github_client(get_file_content_side_effect=RuntimeError("network error"))

        result = await fetch_plan_content(gc, "org/repo", "PROJ-123")

        assert result is None
