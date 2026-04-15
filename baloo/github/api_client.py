"""GitHub API client for fetching PR data and posting reviews."""

from __future__ import annotations

import asyncio
import base64
import logging

import httpx

from baloo.github.auth import GitHubAuth
from baloo.github.discussions import (
    build_discussion_digest,
    build_general_discussion,
    build_review_threads,
)
from baloo.github.models import (
    DiscussionComment,
    DiscussionThread,
    FileChange,
    PRContext,
    PRDiscussionContext,
    PRMetadata,
    ReviewResult,
)

logger = logging.getLogger(__name__)


class GitHubAPIClient:
    """Client for interacting with GitHub API."""

    def __init__(self, installation_id: int):
        """
        Initialize GitHub API client.

        Args:
            installation_id: GitHub App installation ID
        """
        self.installation_id = installation_id
        self.auth = GitHubAuth()
        self.base_url = "https://api.github.com"

    def _get_headers(self) -> dict[str, str]:
        """Get headers for GitHub API requests."""
        token = self.auth.get_installation_token(self.installation_id)
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def get_pr_context(self, repo_full_name: str, pr_number: int) -> PRContext:
        """
        Fetch PR context including files changed and diffs.

        Args:
            repo_full_name: Repository full name (owner/repo)
            pr_number: Pull request number

        Returns:
            PRContext with all PR information
        """
        async with httpx.AsyncClient() as client:
            headers = self._get_headers()

            # Fetch PR details
            pr_url = f"{self.base_url}/repos/{repo_full_name}/pulls/{pr_number}"
            pr_response = await client.get(pr_url, headers=headers)
            pr_response.raise_for_status()
            pr_data = pr_response.json()

            # Fetch files changed
            files_url = f"{pr_url}/files"
            files_data = await self._fetch_paginated_json(client, files_url, headers=headers)

            # Convert to FileChange models
            files_changed = [
                FileChange(
                    filename=file["filename"],
                    status=file["status"],
                    additions=file["additions"],
                    deletions=file["deletions"],
                    changes=file["changes"],
                    patch=file.get("patch"),
                )
                for file in files_data
            ]

            # Get full diff
            # GitHub returns 406 if diff is too large (>30MB or very large PRs)
            diff_response = await client.get(
                pr_url,
                headers={**headers, "Accept": "application/vnd.github.v3.diff"},
            )

            if diff_response.status_code == 406:
                # PR is too large for full diff - construct from individual file patches
                logger.warning(
                    f"PR {repo_full_name}#{pr_number} diff too large (406), "
                    f"constructing from {len(files_changed)} file patches"
                )
                diff_parts = []
                for file in files_changed:
                    if file.patch:
                        diff_parts.append(f"diff --git a/{file.filename} b/{file.filename}")
                        diff_parts.append(file.patch)
                diff = "\n".join(diff_parts) if diff_parts else "# Diff too large to display"
            else:
                diff_response.raise_for_status()
                diff = diff_response.text

            # Fetch discussion data
            review_comments_url = (
                f"{self.base_url}/repos/{repo_full_name}/pulls/{pr_number}/comments"
            )
            issue_comments_url = (
                f"{self.base_url}/repos/{repo_full_name}/issues/{pr_number}/comments"
            )
            reviews_url = f"{self.base_url}/repos/{repo_full_name}/pulls/{pr_number}/reviews"

            review_comments = await self._fetch_paginated_json(
                client, review_comments_url, headers=headers
            )
            issue_comments = await self._fetch_paginated_json(
                client, issue_comments_url, headers=headers
            )
            reviews = await self._fetch_paginated_json(client, reviews_url, headers=headers)

            discussion_threads: list[DiscussionThread] = build_review_threads(review_comments)
            general_comments: list[DiscussionComment] = build_general_discussion(
                issue_comments, reviews
            )
            discussion_digest, awaiting_count = build_discussion_digest(
                discussion_threads, general_comments
            )

            # Fetch guidelines files from the reviewed repo concurrently
            head_sha = pr_data["head"]["sha"]
            agents_md, contributing_md = await asyncio.gather(
                self.get_file_content(repo_full_name, "AGENTS.md", ref=head_sha),
                self.get_file_content(repo_full_name, "CONTRIBUTING.md", ref=head_sha),
            )
            guidelines_parts = [c for c in [agents_md, contributing_md] if c]
            repo_guidelines = "\n\n---\n\n".join(guidelines_parts) if guidelines_parts else None

            metadata = PRMetadata(
                repo_full_name=repo_full_name,
                pr_number=pr_number,
                title=pr_data["title"],
                description=pr_data.get("body"),
                author=pr_data["user"]["login"],
                base_branch=pr_data["base"]["ref"],
                head_branch=pr_data["head"]["ref"],
                head_sha=pr_data["head"]["sha"],
                files_changed=files_changed,
                repo_guidelines=repo_guidelines,
            )

            discussion = PRDiscussionContext(
                threads=discussion_threads,
                issue_comments=general_comments,
                digest=discussion_digest,
                awaiting_response_count=awaiting_count,
            )

            return PRContext(
                metadata=metadata,
                discussion=discussion,
                diff=diff,
            )

    async def post_review(
        self, repo_full_name: str, pr_number: int, review_result: ReviewResult
    ) -> None:
        """
        Post a review to a pull request.

        Args:
            repo_full_name: Repository full name (owner/repo)
            pr_number: Pull request number
            review_result: Review result to post
        """
        import logging

        logger = logging.getLogger(__name__)

        async with httpx.AsyncClient() as client:
            # Determine review event
            # Note: We intentionally never use REQUEST_CHANGES to avoid blocking PRs.
            # Baloo provides feedback via comments but lets humans make merge decisions.
            if review_result.approve:
                event = "APPROVE"
            else:
                event = "COMMENT"

            # Build review payload
            review_payload = {
                "body": review_result.summary,
                "event": event,
                "comments": [
                    {
                        "path": comment.path,
                        "line": comment.line,
                        "body": f"**[{comment.severity}] {comment.category}** - {comment.body}",
                    }
                    for comment in review_result.comments
                ],
            }

            # Post review
            review_url = f"{self.base_url}/repos/{repo_full_name}/pulls/{pr_number}/reviews"

            try:
                response = await client.post(
                    review_url, headers=self._get_headers(), json=review_payload
                )
                response.raise_for_status()
                logger.info(
                    f"Successfully posted review with {len(review_result.comments)} inline comments"
                )

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 422:
                    # GitHub rejected inline comments (line numbers don't match diff)
                    # Fall back to posting summary + issue comments
                    logger.warning(
                        f"Failed to post inline comments (422 error). "
                        f"Falling back to issue comments. Error: {e.response.text}"
                    )

                    # Post summary as general comment
                    await self.post_comment(repo_full_name, pr_number, review_result.summary)

                    # Post each finding as a separate comment
                    for i, comment in enumerate(review_result.comments):
                        comment_body = (
                            f"**[{comment.severity}] {comment.category}** - {comment.path}:{comment.line}\n\n"
                            f"{comment.body}"
                        )
                        await self.post_comment(repo_full_name, pr_number, comment_body)
                        logger.info(f"Posted issue comment {i+1}/{len(review_result.comments)}")

                    logger.info(
                        f"Successfully posted review as {len(review_result.comments)} issue comments"
                    )
                else:
                    # Other HTTP error - re-raise
                    raise

    async def post_comment(self, repo_full_name: str, pr_number: int, comment: str) -> int:
        """
        Post a general comment to a pull request.

        Args:
            repo_full_name: Repository full name (owner/repo)
            pr_number: Pull request number
            comment: Comment text

        Returns:
            The comment ID
        """
        async with httpx.AsyncClient() as client:
            comment_url = f"{self.base_url}/repos/{repo_full_name}/issues/{pr_number}/comments"
            response = await client.post(
                comment_url,
                headers=self._get_headers(),
                json={"body": comment},
            )
            response.raise_for_status()
            return response.json()["id"]

    async def edit_comment(self, repo_full_name: str, comment_id: int, comment: str) -> None:
        """
        Edit an existing comment.

        Args:
            repo_full_name: Repository full name (owner/repo)
            comment_id: The comment ID to edit
            comment: New comment text
        """
        async with httpx.AsyncClient() as client:
            comment_url = f"{self.base_url}/repos/{repo_full_name}/issues/comments/{comment_id}"
            response = await client.patch(
                comment_url,
                headers=self._get_headers(),
                json={"body": comment},
            )
            response.raise_for_status()

    async def reply_to_review_comment(
        self,
        repo_full_name: str,
        review_comment_id: int,
        comment: str,
    ) -> bool:
        """
        Reply to an existing review comment thread.

        Args:
            repo_full_name: Repository full name (owner/repo)
            review_comment_id: ID of the review comment to reply to
            comment: Comment body

        Returns:
            True if reply was successful, False if comment is outdated (404)
        """
        async with httpx.AsyncClient() as client:
            reply_url = (
                f"{self.base_url}/repos/{repo_full_name}/pulls/comments/{review_comment_id}/replies"
            )
            response = await client.post(
                reply_url,
                headers=self._get_headers(),
                json={"body": comment},
            )

            # Handle outdated comments (GitHub returns 404 when comment line is null)
            if response.status_code == 404:
                logger.warning(
                    f"Cannot reply to comment {review_comment_id} - comment is outdated "
                    f"(line no longer exists in latest commit)"
                )
                return False

            response.raise_for_status()
            return True

    async def get_commit_info(self, repo_full_name: str, commit_sha: str) -> dict:
        """
        Fetch information about a specific commit.

        Args:
            repo_full_name: Repository full name (owner/repo)
            commit_sha: Commit SHA

        Returns:
            Dict with commit info including parents, message, and files changed
        """
        async with httpx.AsyncClient() as client:
            url = f"{self.base_url}/repos/{repo_full_name}/commits/{commit_sha}"
            response = await client.get(url, headers=self._get_headers())
            response.raise_for_status()
            return response.json()

    async def is_merge_or_sync_commit(
        self, repo_full_name: str, commit_sha: str, base_branch: str
    ) -> tuple[bool, str]:
        """
        Check if a commit is a merge/sync commit that doesn't warrant a new review.

        This detects:
        1. Merge commits (2+ parents) with messages like "Merge branch 'dev' into feature"
        2. Commits that only merge upstream changes without new PR-specific changes

        Args:
            repo_full_name: Repository full name (owner/repo)
            commit_sha: Commit SHA to check
            base_branch: The base branch of the PR (e.g., 'main', 'dev')

        Returns:
            Tuple of (is_skip_worthy, reason)
        """
        try:
            commit_info = await self.get_commit_info(repo_full_name, commit_sha)

            parents = commit_info.get("parents", [])
            message = commit_info.get("commit", {}).get("message", "").lower()
            files = commit_info.get("files", [])

            # Check if it's a merge commit (2+ parents)
            if len(parents) >= 2:
                # Check for common merge patterns
                merge_patterns = [
                    f"merge branch '{base_branch}'",
                    f'merge branch "{base_branch}"',
                    f"merge {base_branch} into",
                    "merge pull request",
                    "merge remote-tracking branch",
                ]

                for pattern in merge_patterns:
                    if pattern in message:
                        # If it's a pure merge with no file changes, definitely skip
                        if not files:
                            return True, "merge commit with no file changes"

                        # If it only has a few conflict resolution files, likely just a sync
                        if len(files) <= 3:
                            return (
                                True,
                                f"merge commit with only {len(files)} file(s) (conflict resolution)",
                            )

            return False, ""

        except Exception as e:
            logger.warning(f"Failed to check commit info for {commit_sha}: {e}")
            return False, ""

    async def get_file_content(
        self, repo_full_name: str, path: str, ref: str | None = None
    ) -> str | None:
        """
        Fetch the content of a file from a repository.

        Args:
            repo_full_name: Repository full name (owner/repo)
            path: Path to the file within the repository
            ref: Git reference (branch, tag, or commit SHA). Defaults to repo default branch.

        Returns:
            File content as string, or None if file not found
        """
        async with httpx.AsyncClient() as client:
            url = f"{self.base_url}/repos/{repo_full_name}/contents/{path}"
            params = {}
            if ref:
                params["ref"] = ref

            try:
                response = await client.get(url, headers=self._get_headers(), params=params)

                if response.status_code == 404:
                    logger.debug(f"File not found: {repo_full_name}/{path}")
                    return None

                response.raise_for_status()
                data = response.json()

                # GitHub returns base64-encoded content for files
                if data.get("type") == "file" and data.get("content"):
                    content = base64.b64decode(data["content"]).decode("utf-8")
                    return content

                logger.warning(f"Unexpected content type for {path}: {data.get('type')}")
                return None

            except httpx.HTTPStatusError as e:
                logger.warning(f"Failed to fetch file {path}: {e}")
                return None

    async def list_directory(
        self, repo_full_name: str, path: str, ref: str | None = None
    ) -> list[str]:
        """
        List files in a directory.

        Args:
            repo_full_name: Repository full name (owner/repo)
            path: Path to the directory
            ref: Git reference (branch, tag, or commit SHA)

        Returns:
            List of filenames in the directory, or empty list if not found
        """
        async with httpx.AsyncClient() as client:
            url = f"{self.base_url}/repos/{repo_full_name}/contents/{path}"
            params = {}
            if ref:
                params["ref"] = ref

            try:
                response = await client.get(url, headers=self._get_headers(), params=params)

                if response.status_code == 404:
                    return []

                response.raise_for_status()
                data = response.json()

                # GitHub returns a list of items for directories
                if isinstance(data, list):
                    return [item["name"] for item in data if item.get("type") == "file"]

                return []

            except httpx.HTTPStatusError:
                return []

    async def _fetch_paginated_json(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        headers: dict[str, str],
    ) -> list[dict]:
        """Fetch all pages from a GitHub REST collection endpoint."""
        results: list[dict] = []
        page = 1

        while True:
            response = await client.get(
                url, headers=headers, params={"per_page": 100, "page": page}
            )
            response.raise_for_status()
            data = response.json()
            if not data:
                break

            results.extend(data)
            if len(data) < 100:
                break
            page += 1

        return results
