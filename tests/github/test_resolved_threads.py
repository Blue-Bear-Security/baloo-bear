"""Tests for fetching resolved thread state from the GraphQL API."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from baloo.github.api_client import GitHubAPIClient, _apply_resolved_thread_state
from baloo.github.discussions import build_discussion_digest
from baloo.github.models import DiscussionComment, DiscussionThread


def _graphql_response(nodes: list[dict], has_next: bool = False, cursor: str = "c1") -> dict:
    """Build a GraphQL response payload."""
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {
                            "hasNextPage": has_next,
                            "endCursor": cursor,
                        },
                        "nodes": nodes,
                    }
                }
            }
        }
    }


def _thread_node(comment_db_id: int, is_resolved: bool, is_outdated: bool = False) -> dict:
    return {
        "isResolved": is_resolved,
        "isOutdated": is_outdated,
        "comments": {"nodes": [{"databaseId": comment_db_id}]},
    }


def _mock_response(body: dict, status_code: int = 200):
    """Build a mock httpx response with a sync .json() method."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    resp.json.return_value = body
    return resp


class TestFetchResolvedThreadIds:
    @pytest.fixture(autouse=True)
    def _patch_auth(self, monkeypatch):
        monkeypatch.setattr(
            "baloo.github.api_client.GitHubAuth.get_installation_token",
            lambda self, iid: "fake-token",
        )

    @pytest.mark.asyncio
    async def test_returns_resolved_ids(self):
        body = _graphql_response(
            [
                _thread_node(100, is_resolved=True),
                _thread_node(200, is_resolved=False),
                _thread_node(300, is_resolved=True),
            ]
        )

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=_mock_response(body))
            mock_client_cls.return_value = mock_client

            client = GitHubAPIClient(installation_id=1)
            ids = await client.fetch_resolved_thread_ids("owner/repo", 42)

        resolved_ids, outdated_ids, _ = ids
        assert resolved_ids == {100, 300}
        assert outdated_ids == set()

    @pytest.mark.asyncio
    async def test_paginates(self):
        page1 = _graphql_response([_thread_node(10, True)], has_next=True, cursor="page2")
        page2 = _graphql_response([_thread_node(20, True)], has_next=False)

        call_count = 0

        async def fake_post(url, **kwargs):
            nonlocal call_count
            call_count += 1
            return _mock_response(page1 if call_count == 1 else page2)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = fake_post
            mock_client_cls.return_value = mock_client

            client = GitHubAPIClient(installation_id=1)
            ids = await client.fetch_resolved_thread_ids("owner/repo", 1)

        resolved_ids, outdated_ids, _ = ids
        assert resolved_ids == {10, 20}
        assert outdated_ids == set()
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_returns_empty_on_graphql_error(self):
        body = {"errors": [{"message": "something went wrong"}]}

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=_mock_response(body))
            mock_client_cls.return_value = mock_client

            client = GitHubAPIClient(installation_id=1)
            ids = await client.fetch_resolved_thread_ids("owner/repo", 1)

        assert ids == (set(), set(), {})

    @pytest.mark.asyncio
    async def test_returns_empty_on_http_error(self):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "500", request=httpx.Request("POST", "url"), response=httpx.Response(500)
                )
            )
            mock_client_cls.return_value = mock_client

            client = GitHubAPIClient(installation_id=1)
            ids = await client.fetch_resolved_thread_ids("owner/repo", 1)

        assert ids == (set(), set(), {})

    @pytest.mark.asyncio
    async def test_logs_exception_type_when_resolved_thread_fetch_fails(self, caplog):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException(""))
            mock_client_cls.return_value = mock_client

            client = GitHubAPIClient(installation_id=1)
            with caplog.at_level("WARNING", logger="baloo.github.api_client"):
                ids = await client.fetch_resolved_thread_ids("owner/repo", 1)

        assert ids == (set(), set(), {})
        assert "TimeoutException" in caplog.text

    @pytest.mark.asyncio
    async def test_no_resolved_threads(self):
        body = _graphql_response(
            [
                _thread_node(100, is_resolved=False),
                _thread_node(200, is_resolved=False),
            ]
        )

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=_mock_response(body))
            mock_client_cls.return_value = mock_client

            client = GitHubAPIClient(installation_id=1)
            ids = await client.fetch_resolved_thread_ids("owner/repo", 1)

        assert ids == (set(), set(), {})

    @pytest.mark.asyncio
    async def test_separates_outdated_from_resolved(self):
        body = _graphql_response(
            [
                _thread_node(100, is_resolved=True),
                _thread_node(200, is_resolved=False, is_outdated=True),
                _thread_node(300, is_resolved=False),
            ]
        )

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=_mock_response(body))
            mock_client_cls.return_value = mock_client

            client = GitHubAPIClient(installation_id=1)
            resolved_ids, outdated_ids, _ = await client.fetch_resolved_thread_ids("owner/repo", 42)

        assert resolved_ids == {100}
        assert outdated_ids == {200}


class TestApplyResolvedThreadState:
    def test_resolved_baloo_thread_is_not_counted_as_awaiting_response(self):
        """GraphQL-resolved threads should not remain open just because Baloo commented last."""
        now = datetime.now(timezone.utc)
        thread = DiscussionThread(
            id=100,
            path="file.py",
            line=10,
            comments=[
                DiscussionComment(
                    id=100,
                    author="baloo-code-reviewer[bot]",
                    body="**[HIGH] Bugs** - Existing issue",
                    created_at=now,
                    updated_at=now,
                    source="review_comment",
                    is_baloo=True,
                    path="file.py",
                    line=10,
                )
            ],
            is_baloo_thread=True,
            awaiting_response=True,
            resolved=False,
            last_activity=now,
            root_comment_id=100,
        )

        _apply_resolved_thread_state([thread], {100})
        _, awaiting_count = build_discussion_digest([thread], [])

        assert thread.resolved is True
        assert thread.awaiting_response is False
        assert awaiting_count == 0
