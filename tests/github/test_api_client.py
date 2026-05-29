"""Comprehensive tests for GitHubAPIClient — methods not covered by existing test files."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from baloo.github.api_client import GitHubAPIClient
from baloo.github.models import ReviewComment, ReviewResult


def _mock_response(body=None, status_code: int = 200, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = body if body is not None else {}

    if status_code >= 400:
        error = httpx.HTTPStatusError(
            f"HTTP {status_code}",
            request=MagicMock(),
            response=resp,
        )
        resp.raise_for_status.side_effect = error
    else:
        resp.raise_for_status = MagicMock()

    return resp


def _make_client() -> tuple[GitHubAPIClient, AsyncMock]:
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    auth = MagicMock()
    auth.get_installation_token.return_value = "tok"
    client = GitHubAPIClient(installation_id=1, http_client=mock_http, auth=auth)
    return client, mock_http


def _valid_comment(path: str, line: int) -> ReviewComment:
    return ReviewComment(path=path, line=line, body="note", severity="LOW", category="Quality")


def _pr_data() -> dict:
    return {
        "title": "My PR",
        "body": "PR description",
        "user": {"login": "dev"},
        "base": {"ref": "main"},
        "head": {"ref": "feature", "sha": "headsha"},
    }


def _empty_graphql_response() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [],
                    }
                }
            }
        }
    }
    return resp


class TestPostComment:
    @pytest.mark.asyncio
    async def test_returns_comment_id(self):
        client, mock_http = _make_client()
        mock_http.post.return_value = _mock_response({"id": 99})

        result = await client.post_comment("owner/repo", 42, "hello")

        assert result == 99
        mock_http.post.assert_called_once()
        (url,) = mock_http.post.call_args[0]
        assert "/issues/42/comments" in url
        assert mock_http.post.call_args[1]["json"] == {"body": "hello"}

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self):
        client, mock_http = _make_client()
        mock_http.post.return_value = _mock_response(status_code=403)

        with pytest.raises(httpx.HTTPStatusError):
            await client.post_comment("owner/repo", 42, "hello")


class TestEditComment:
    @pytest.mark.asyncio
    async def test_patches_correct_url(self):
        client, mock_http = _make_client()
        mock_http.patch.return_value = _mock_response()

        await client.edit_comment("owner/repo", 7, "updated text")

        mock_http.patch.assert_called_once()
        (url,) = mock_http.patch.call_args[0]
        assert "/issues/comments/7" in url
        assert mock_http.patch.call_args[1]["json"] == {"body": "updated text"}


class TestReplyToReviewComment:
    @pytest.mark.asyncio
    async def test_returns_true_on_success(self):
        client, mock_http = _make_client()
        mock_http.post.return_value = _mock_response(status_code=201)

        result = await client.reply_to_review_comment("owner/repo", 42, 10, "LGTM")

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_404(self):
        client, mock_http = _make_client()
        resp = MagicMock()
        resp.status_code = 404
        resp.raise_for_status = MagicMock()
        mock_http.post.return_value = resp

        result = await client.reply_to_review_comment("owner/repo", 42, 10, "LGTM")

        assert result is False

    @pytest.mark.asyncio
    async def test_raises_on_non_404_error(self):
        client, mock_http = _make_client()
        mock_http.post.return_value = _mock_response(status_code=500)

        with pytest.raises(httpx.HTTPStatusError):
            await client.reply_to_review_comment("owner/repo", 42, 10, "LGTM")


class TestGetFileContent:
    @pytest.mark.asyncio
    async def test_returns_decoded_content(self):
        content = base64.b64encode(b"file contents here").decode()
        client, mock_http = _make_client()
        mock_http.get.return_value = _mock_response({"type": "file", "content": content})

        result = await client.get_file_content("owner/repo", "README.md")

        assert result == "file contents here"
        (url,) = mock_http.get.call_args[0]
        assert "/contents/README.md" in url

    @pytest.mark.asyncio
    async def test_returns_none_on_404(self):
        client, mock_http = _make_client()
        resp = MagicMock()
        resp.status_code = 404
        resp.raise_for_status = MagicMock()
        mock_http.get.return_value = resp

        result = await client.get_file_content("owner/repo", "missing.md")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_unexpected_type(self):
        client, mock_http = _make_client()
        mock_http.get.return_value = _mock_response({"type": "dir", "content": None})

        result = await client.get_file_content("owner/repo", "somedir")

        assert result is None

    @pytest.mark.asyncio
    async def test_passes_ref_as_param(self):
        content = base64.b64encode(b"versioned").decode()
        client, mock_http = _make_client()
        mock_http.get.return_value = _mock_response({"type": "file", "content": content})

        await client.get_file_content("owner/repo", "file.py", ref="abc123")

        params = mock_http.get.call_args[1]["params"]
        assert params["ref"] == "abc123"

    @pytest.mark.asyncio
    async def test_returns_none_on_http_error(self):
        client, mock_http = _make_client()
        mock_http.get.return_value = _mock_response(status_code=500)

        result = await client.get_file_content("owner/repo", "file.py")

        assert result is None


class TestListDirectory:
    @pytest.mark.asyncio
    async def test_returns_file_names(self):
        client, mock_http = _make_client()
        mock_http.get.return_value = _mock_response(
            [
                {"name": "foo.py", "type": "file"},
                {"name": "subdir", "type": "dir"},
                {"name": "bar.py", "type": "file"},
            ]
        )

        result = await client.list_directory("owner/repo", "src/")

        assert result == ["foo.py", "bar.py"]

    @pytest.mark.asyncio
    async def test_returns_empty_on_404(self):
        client, mock_http = _make_client()
        resp = MagicMock()
        resp.status_code = 404
        resp.raise_for_status = MagicMock()
        mock_http.get.return_value = resp

        result = await client.list_directory("owner/repo", "nonexistent/")

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_response_is_not_list(self):
        client, mock_http = _make_client()
        mock_http.get.return_value = _mock_response({"type": "file"})

        result = await client.list_directory("owner/repo", "file.py")

        assert result == []


class TestGetCommitInfo:
    @pytest.mark.asyncio
    async def test_returns_commit_data(self):
        commit_data = {
            "sha": "abc123",
            "parents": [{"sha": "def456"}],
            "commit": {"message": "fix"},
        }
        client, mock_http = _make_client()
        mock_http.get.return_value = _mock_response(commit_data)

        result = await client.get_commit_info("owner/repo", "abc123")

        assert result == commit_data
        (url,) = mock_http.get.call_args[0]
        assert "/commits/abc123" in url


class TestCommitIsAncestorOfBranch:
    @pytest.mark.asyncio
    async def test_returns_true_when_ahead(self):
        client, mock_http = _make_client()
        mock_http.get.return_value = _mock_response({"status": "ahead"})

        result = await client._commit_is_ancestor_of_branch("owner/repo", "abc123", "main")

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_true_when_identical(self):
        client, mock_http = _make_client()
        mock_http.get.return_value = _mock_response({"status": "identical"})

        result = await client._commit_is_ancestor_of_branch("owner/repo", "abc123", "main")

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_diverged(self):
        client, mock_http = _make_client()
        mock_http.get.return_value = _mock_response({"status": "diverged"})

        result = await client._commit_is_ancestor_of_branch("owner/repo", "abc123", "main")

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_non_200(self):
        client, mock_http = _make_client()
        resp = MagicMock()
        resp.status_code = 404
        mock_http.get.return_value = resp

        result = await client._commit_is_ancestor_of_branch("owner/repo", "abc123", "main")

        assert result is False


class TestFetchReviewComments:
    @pytest.mark.asyncio
    async def test_returns_comments(self):
        comments = [{"id": 1, "body": "comment"}]
        client, mock_http = _make_client()
        mock_http.get.return_value = _mock_response(comments)

        result = await client.fetch_review_comments("owner/repo", 42)

        assert result == comments
        (url,) = mock_http.get.call_args[0]
        assert "/pulls/42/comments" in url


class TestFetchPaginatedJson:
    @pytest.mark.asyncio
    async def test_returns_single_page(self):
        items = [{"id": i} for i in range(5)]
        client, mock_http = _make_client()
        mock_http.get.return_value = _mock_response(items)

        result = await client._fetch_paginated_json("https://api.github.com/some/endpoint")

        assert result == items
        mock_http.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_paginates_until_partial_page(self):
        page1 = [{"id": i} for i in range(100)]
        page2 = [{"id": i} for i in range(100, 130)]
        client, mock_http = _make_client()
        mock_http.get.side_effect = [
            _mock_response(page1),
            _mock_response(page2),
        ]

        result = await client._fetch_paginated_json("https://api.github.com/some/endpoint")

        assert len(result) == 130
        assert mock_http.get.call_count == 2

    @pytest.mark.asyncio
    async def test_stops_on_empty_response(self):
        client, mock_http = _make_client()
        mock_http.get.return_value = _mock_response([])

        result = await client._fetch_paginated_json("https://api.github.com/some/endpoint")

        assert result == []
        mock_http.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_stops_on_404_mid_pagination(self):
        # GitHub can return 404 for out-of-bounds pages (e.g. PR files endpoint)
        page1 = [{"id": i} for i in range(100)]
        page2 = [{"id": i} for i in range(100, 200)]
        client, mock_http = _make_client()
        mock_http.get.side_effect = [
            _mock_response(page1),
            _mock_response(page2),
            _mock_response(status_code=404),
        ]

        result = await client._fetch_paginated_json("https://api.github.com/some/endpoint")

        assert len(result) == 200
        assert mock_http.get.call_count == 3

    @pytest.mark.asyncio
    async def test_raises_on_404_first_page(self):
        # A 404 on page 1 is a genuine error (bad URL, deleted PR) — must not swallow it
        client, mock_http = _make_client()
        mock_http.get.return_value = _mock_response(status_code=404)

        with pytest.raises(httpx.HTTPStatusError):
            await client._fetch_paginated_json("https://api.github.com/some/endpoint")


class TestGetChangedScopeBetweenCommits:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_shas(self):
        client, mock_http = _make_client()

        paths, scope, files, diff = await client.get_changed_scope_between_commits(
            "owner/repo", "", "head123"
        )

        assert paths == set()
        assert scope == {}
        assert files == []
        assert diff == ""
        mock_http.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_changed_paths_and_diff(self):
        compare_data = {
            "files": [
                {
                    "filename": "src/main.py",
                    "status": "modified",
                    "additions": 5,
                    "deletions": 2,
                    "changes": 7,
                    "patch": "@@ -1,3 +1,6 @@\n context\n+added\n context",
                },
                {
                    "filename": "tests/test_main.py",
                    "status": "added",
                    "additions": 10,
                    "deletions": 0,
                    "changes": 10,
                    "patch": "@@ -0,0 +1,10 @@\n+new test",
                },
            ]
        }
        client, mock_http = _make_client()
        mock_http.get.return_value = _mock_response(compare_data)

        paths, scope, files, diff = await client.get_changed_scope_between_commits(
            "owner/repo", "base123", "head456"
        )

        assert "src/main.py" in paths
        assert "tests/test_main.py" in paths
        assert len(files) == 2
        assert files[0].filename == "src/main.py"
        assert "diff --git a/src/main.py" in diff

    @pytest.mark.asyncio
    async def test_skips_files_without_patch(self):
        compare_data = {
            "files": [
                {
                    "filename": "binary.png",
                    "status": "modified",
                    "additions": 0,
                    "deletions": 0,
                    "changes": 0,
                    # no "patch" key
                }
            ]
        }
        client, mock_http = _make_client()
        mock_http.get.return_value = _mock_response(compare_data)

        paths, scope, files, diff = await client.get_changed_scope_between_commits(
            "owner/repo", "base123", "head456"
        )

        assert "binary.png" in paths
        assert len(files) == 1
        assert diff == ""
        assert scope == {}


class TestGetPRContext:
    @pytest.mark.asyncio
    async def test_returns_pr_context_with_basic_data(self):
        """Happy path: all API calls succeed, diff returned normally."""
        client, mock_http = _make_client()

        agents_content = base64.b64encode(b"# AGENTS.md content").decode()

        # Call order for get_pr_context (GET calls):
        # 1. GET /repos/owner/repo/pulls/42  (PR data)
        # 2. GET /repos/owner/repo/pulls/42/files (paginated)
        # 3. GET /repos/owner/repo/pulls/42 Accept: diff  (raw diff)
        # 4. GET /repos/owner/repo/pulls/42/comments (paginated)
        # 5. GET /repos/owner/repo/issues/42/comments (paginated)
        # 6. GET /repos/owner/repo/pulls/42/reviews (paginated)
        # 7. GET /repos/owner/repo/contents/AGENTS.md (asyncio.gather)
        # 8. GET /repos/owner/repo/contents/CONTRIBUTING.md (asyncio.gather)
        # 9. GET /repos/owner/repo/pulls/42/commits (paginated, asyncio.gather)
        # POST: graphql fetch_resolved_thread_ids

        diff_resp = MagicMock()
        diff_resp.status_code = 200
        diff_resp.raise_for_status = MagicMock()
        diff_resp.text = "diff --git a/src/foo.py b/src/foo.py\n@@ -1 +1 @@\n+new line"

        mock_http.get.side_effect = [
            _mock_response(_pr_data()),
            _mock_response(
                [
                    {
                        "filename": "src/foo.py",
                        "status": "modified",
                        "additions": 3,
                        "deletions": 1,
                        "changes": 4,
                        "patch": "@@ -1 +1 @@\n+new line",
                    }
                ]
            ),
            diff_resp,
            _mock_response([]),  # review comments
            _mock_response([]),  # issue comments
            _mock_response([]),  # reviews
            _mock_response({"type": "file", "content": agents_content}),  # AGENTS.md
            _mock_response(status_code=404),  # CONTRIBUTING.md not found
            _mock_response([{"commit": {"message": "initial commit\n\ndetails"}}]),  # commits
        ]
        mock_http.post.side_effect = [_empty_graphql_response()]

        result = await client.get_pr_context("owner/repo", 42)

        assert result.metadata.title == "My PR"
        assert result.metadata.author == "dev"
        assert result.metadata.base_branch == "main"
        assert result.metadata.head_sha == "headsha"
        assert len(result.metadata.files_changed) == 1
        assert result.metadata.files_changed[0].filename == "src/foo.py"
        assert "new line" in result.diff
        assert result.metadata.repo_guidelines == "# AGENTS.md content"
        assert result.metadata.commit_messages == ["initial commit"]

    @pytest.mark.asyncio
    async def test_handles_406_diff_by_constructing_from_patches(self):
        """When GitHub returns 406 for diff, fall back to file patches."""
        client, mock_http = _make_client()

        mock_http.get.side_effect = [
            _mock_response(_pr_data()),
            _mock_response(
                [
                    {
                        "filename": "large_file.py",
                        "status": "modified",
                        "additions": 100,
                        "deletions": 50,
                        "changes": 150,
                        "patch": "@@ -1 +1 @@\n+changed",
                    }
                ]
            ),
            _mock_response(status_code=406),  # diff too large
            _mock_response([]),
            _mock_response([]),
            _mock_response([]),
            _mock_response(status_code=404),  # AGENTS.md
            _mock_response(status_code=404),  # CONTRIBUTING.md
            _mock_response([]),
        ]
        mock_http.post.side_effect = [_empty_graphql_response()]

        result = await client.get_pr_context("owner/repo", 42)

        assert "diff --git a/large_file.py" in result.diff
        assert "@@ -1 +1 @@" in result.diff

    @pytest.mark.asyncio
    async def test_no_guidelines_when_both_files_missing(self):
        client, mock_http = _make_client()

        diff_resp = MagicMock()
        diff_resp.status_code = 200
        diff_resp.raise_for_status = MagicMock()
        diff_resp.text = "diff text"

        mock_http.get.side_effect = [
            _mock_response(_pr_data()),
            _mock_response([]),
            diff_resp,
            _mock_response([]),
            _mock_response([]),
            _mock_response([]),
            _mock_response(status_code=404),  # AGENTS.md
            _mock_response(status_code=404),  # CONTRIBUTING.md
            _mock_response([]),
        ]
        mock_http.post.side_effect = [_empty_graphql_response()]

        result = await client.get_pr_context("owner/repo", 42)

        assert result.metadata.repo_guidelines is None


class TestPostReviewEdgeCases:
    @pytest.mark.asyncio
    async def test_422_from_github_returns_github_rejected(self):
        """GitHub rejecting the review with 422 returns github_rejected=True instead of raising."""
        diff = "\n".join(
            [
                "diff --git a/file.py b/file.py",
                "@@ -1,3 +1,3 @@",
                " ctx",
                "+line",
                " ctx",
            ]
        )
        comment = _valid_comment("file.py", 2)
        client, mock_http = _make_client()

        reject_resp = MagicMock()
        reject_resp.status_code = 422
        reject_resp.text = "Validation failed"
        reject_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "422", request=MagicMock(), response=reject_resp
        )
        mock_http.post.return_value = reject_resp

        result = await client.post_review(
            "owner/repo",
            42,
            ReviewResult(summary="summary", comments=[comment]),
            diff=diff,
        )

        assert result.github_rejected is True
        assert result.posted == 0

    @pytest.mark.asyncio
    async def test_non_422_http_error_reraises(self):
        diff = "\n".join(
            [
                "diff --git a/file.py b/file.py",
                "@@ -1,3 +1,3 @@",
                " ctx",
                "+line",
                " ctx",
            ]
        )
        comment = _valid_comment("file.py", 2)
        client, mock_http = _make_client()
        mock_http.post.return_value = _mock_response(status_code=500)

        with pytest.raises(httpx.HTTPStatusError):
            await client.post_review(
                "owner/repo",
                42,
                ReviewResult(summary="s", comments=[comment]),
                diff=diff,
            )


class TestFetchResolvedThreadIdsEdgeCases:
    @pytest.mark.asyncio
    async def test_skips_node_without_database_id(self):
        """Nodes with missing databaseId are skipped without error."""
        client, mock_http = _make_client()
        mock_http.post.return_value = _mock_response(
            {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "nodes": [
                                    {
                                        "id": "PRT_1",
                                        "isResolved": True,
                                        "isOutdated": False,
                                        "comments": {"nodes": []},  # no databaseId
                                    }
                                ],
                            }
                        }
                    }
                }
            }
        )

        resolved, outdated, node_map = await client.fetch_resolved_thread_ids("owner/repo", 1)

        assert resolved == set()
        assert outdated == set()
        assert node_map == {}

    @pytest.mark.asyncio
    async def test_classifies_outdated_threads(self):
        client, mock_http = _make_client()
        mock_http.post.return_value = _mock_response(
            {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "nodes": [
                                    {
                                        "id": "PRT_outdated",
                                        "isResolved": False,
                                        "isOutdated": True,
                                        "comments": {"nodes": [{"databaseId": 555}]},
                                    }
                                ],
                            }
                        }
                    }
                }
            }
        )

        resolved, outdated, node_map = await client.fetch_resolved_thread_ids("owner/repo", 1)

        assert 555 not in resolved
        assert 555 in outdated
        assert node_map[555] == "PRT_outdated"
