"""Tests for resolve_review_thread GraphQL mutation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from baloo.github.api_client import GitHubAPIClient


def _mock_response(body: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = body or {}
    return resp


def _make_client() -> tuple[GitHubAPIClient, AsyncMock]:
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    auth = MagicMock()
    auth.get_installation_token.return_value = "tok"
    client = GitHubAPIClient(installation_id=1, http_client=mock_http, auth=auth)
    return client, mock_http


@pytest.mark.asyncio
async def test_resolve_review_thread_success():
    client, mock_http = _make_client()
    mock_http.post.return_value = _mock_response(
        {"data": {"resolveReviewThread": {"thread": {"id": "PRT_x", "isResolved": True}}}}
    )

    result = await client.resolve_review_thread("PRT_x")

    assert result is True
    call_kwargs = mock_http.post.call_args
    body = call_kwargs[1]["json"]
    assert "resolveReviewThread" in body["query"]
    assert body["variables"]["threadId"] == "PRT_x"


@pytest.mark.asyncio
async def test_resolve_review_thread_graphql_error_returns_false():
    client, mock_http = _make_client()
    mock_http.post.return_value = _mock_response({"errors": [{"message": "not found"}]})

    result = await client.resolve_review_thread("PRT_bad")

    assert result is False


@pytest.mark.asyncio
async def test_resolve_review_thread_http_exception_returns_false():
    client, mock_http = _make_client()
    mock_http.post.side_effect = Exception("network error")

    result = await client.resolve_review_thread("PRT_x")

    assert result is False
