"""Tests for resolve_review_thread GraphQL mutation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from baloo.github.api_client import GitHubAPIClient


@pytest.mark.asyncio
async def test_resolve_review_thread_success():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "data": {"resolveReviewThread": {"thread": {"id": "PRT_x", "isResolved": True}}}
    }

    with (
        patch("httpx.AsyncClient") as mock_client_cls,
        patch(
            "baloo.github.auth.GitHubAuth.get_installation_token",
            return_value="tok",
        ),
    ):
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_http

        client = GitHubAPIClient(installation_id=1)
        result = await client.resolve_review_thread("PRT_x")

    assert result is True
    call_kwargs = mock_http.post.call_args
    body = call_kwargs[1]["json"]
    assert "resolveReviewThread" in body["query"]
    assert body["variables"]["threadId"] == "PRT_x"


@pytest.mark.asyncio
async def test_resolve_review_thread_graphql_error_returns_false():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"errors": [{"message": "not found"}]}

    with (
        patch("httpx.AsyncClient") as mock_client_cls,
        patch(
            "baloo.github.auth.GitHubAuth.get_installation_token",
            return_value="tok",
        ),
    ):
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_http

        client = GitHubAPIClient(installation_id=1)
        result = await client.resolve_review_thread("PRT_bad")

    assert result is False


@pytest.mark.asyncio
async def test_resolve_review_thread_http_exception_returns_false():
    with (
        patch("httpx.AsyncClient") as mock_client_cls,
        patch(
            "baloo.github.auth.GitHubAuth.get_installation_token",
            return_value="tok",
        ),
    ):
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(side_effect=Exception("network error"))
        mock_client_cls.return_value = mock_http

        client = GitHubAPIClient(installation_id=1)
        result = await client.resolve_review_thread("PRT_x")

    assert result is False
