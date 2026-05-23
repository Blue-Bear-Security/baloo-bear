"""GitHub API client for fetching PR data and posting reviews."""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from dataclasses import dataclass

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
    ReviewComment,
    ReviewResult,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DroppedReviewComment:
    """Review comment that could not be placed on the GitHub diff."""

    comment: ReviewComment
    reason: str
    nearest_valid_line: int | None = None


@dataclass(frozen=True)
class PostedReviewResult:
    """Outcome of posting a pull request review."""

    attempted: int
    posted: int
    dropped: list[DroppedReviewComment]
    github_rejected: bool = False


# Matches unified-diff hunk headers: @@ -old_start[,old_count] +new_start[,new_count] @@
_HUNK_RE = re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _valid_diff_lines(diff: str) -> dict[str, set[int]]:
    """Parse a unified diff and return the set of commentable line numbers per file.

    GitHub only accepts review comments on lines that appear in a diff
    hunk.  For each hunk we walk the lines and track the new-file line
    counter (incremented for context and addition lines, skipped for
    deletion lines).

    Returns:
        Mapping of file path → set of valid new-side line numbers.
    """
    result: dict[str, set[int]] = {}
    current_file: str | None = None
    current_lines: set[int] = set()
    line_no = 0

    for raw in diff.split("\n"):
        if raw.startswith("diff --git"):
            # Save previous file
            if current_file is not None:
                result[current_file] = current_lines
            # Parse new file path from "diff --git a/... b/path"
            parts = raw.split(" b/", 1)
            current_file = parts[1] if len(parts) == 2 else None
            current_lines = set()
            line_no = 0
            continue

        m = _HUNK_RE.match(raw)
        if m:
            line_no = int(m.group(1))
            continue

        if line_no == 0:
            # Before first hunk (file metadata lines)
            continue

        if raw.startswith("-"):
            # Deletion — not in new file, don't increment
            pass
        elif raw.startswith("+"):
            # Addition — valid commentable line
            current_lines.add(line_no)
            line_no += 1
        else:
            # Context line — also valid for comments
            current_lines.add(line_no)
            line_no += 1

    if current_file is not None:
        result[current_file] = current_lines

    return result


def _apply_resolved_thread_state(
    discussion_threads: list[DiscussionThread],
    resolved_ids: set[int],
    outdated_ids: set[int] | None = None,
    thread_node_ids: dict[int, str] | None = None,
) -> None:
    """Overlay GitHub's authoritative resolved/outdated state onto REST-built threads."""
    for thread in discussion_threads:
        if thread_node_ids and thread.root_comment_id is not None:
            thread.node_id = thread_node_ids.get(thread.root_comment_id)
        if thread.root_comment_id in resolved_ids:
            thread.resolved = True
            thread.awaiting_response = False
        elif outdated_ids and thread.root_comment_id in outdated_ids:
            thread.outdated = True
            thread.awaiting_response = False


def _enum_value(value) -> str:
    """Return enum value or string form for logging."""
    return value.value if hasattr(value, "value") else str(value)


class GitHubAPIClient:
    """Client for interacting with GitHub API."""

    def __init__(
        self,
        installation_id: int,
        http_client: httpx.AsyncClient | None = None,
        auth: GitHubAuth | None = None,
    ):
        self.installation_id = installation_id
        self.auth = auth or GitHubAuth()
        self.base_url = "https://api.github.com"
        self._http = http_client or httpx.AsyncClient()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> GitHubAPIClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

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
        headers = self._get_headers()

        pr_url = f"{self.base_url}/repos/{repo_full_name}/pulls/{pr_number}"
        pr_response = await self._http.get(pr_url, headers=headers)
        pr_response.raise_for_status()
        pr_data = pr_response.json()

        files_url = f"{pr_url}/files"
        files_data = await self._fetch_paginated_json(files_url)

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

        diff_response = await self._http.get(
            pr_url,
            headers={**headers, "Accept": "application/vnd.github.v3.diff"},
        )

        if diff_response.status_code == 406:
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

        review_comments_url = f"{self.base_url}/repos/{repo_full_name}/pulls/{pr_number}/comments"
        issue_comments_url = f"{self.base_url}/repos/{repo_full_name}/issues/{pr_number}/comments"
        reviews_url = f"{self.base_url}/repos/{repo_full_name}/pulls/{pr_number}/reviews"

        review_comments = await self._fetch_paginated_json(review_comments_url)
        issue_comments = await self._fetch_paginated_json(issue_comments_url)
        reviews = await self._fetch_paginated_json(reviews_url)

        discussion_threads: list[DiscussionThread] = build_review_threads(review_comments)

        resolved_ids, outdated_ids, thread_node_ids = await self.fetch_resolved_thread_ids(
            repo_full_name, pr_number
        )
        _apply_resolved_thread_state(
            discussion_threads, resolved_ids, outdated_ids, thread_node_ids
        )

        general_comments: list[DiscussionComment] = build_general_discussion(
            issue_comments, reviews
        )
        discussion_digest, awaiting_count = build_discussion_digest(
            discussion_threads, general_comments
        )

        head_sha = pr_data["head"]["sha"]
        commits_url = f"{self.base_url}/repos/{repo_full_name}/pulls/{pr_number}/commits"
        agents_md, contributing_md, commits_data = await asyncio.gather(
            self.get_file_content(repo_full_name, "AGENTS.md", ref=head_sha),
            self.get_file_content(repo_full_name, "CONTRIBUTING.md", ref=head_sha),
            self._fetch_paginated_json(commits_url),
        )
        guidelines_parts = [c for c in [agents_md, contributing_md] if c]
        repo_guidelines = "\n\n---\n\n".join(guidelines_parts) if guidelines_parts else None
        commit_messages = [
            c["commit"]["message"].split("\n")[0] for c in commits_data if c.get("commit")
        ]

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
            commit_messages=commit_messages,
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

    async def get_changed_scope_between_commits(
        self, repo_full_name: str, base_sha: str, head_sha: str
    ) -> tuple[set[str], dict[str, set[int]], list[FileChange], str]:
        """Return latest-push changed files, line scope, and scoped diff."""
        if not base_sha or not head_sha:
            return set(), {}, [], ""

        compare_url = f"{self.base_url}/repos/{repo_full_name}/compare/{base_sha}...{head_sha}"
        response = await self._http.get(compare_url, headers=self._get_headers())
        response.raise_for_status()
        compare_data = response.json()

        files = compare_data.get("files", [])
        changed_paths = {file.get("filename") for file in files if file.get("filename")}
        diff_parts: list[str] = []
        changed_file_models: list[FileChange] = []
        for file in files:
            filename = file.get("filename")
            if filename:
                changed_file_models.append(
                    FileChange(
                        filename=filename,
                        status=file.get("status", "modified"),
                        additions=file.get("additions", 0),
                        deletions=file.get("deletions", 0),
                        changes=file.get("changes", 0),
                        patch=file.get("patch"),
                    )
                )
            patch = file.get("patch")
            if not filename or not patch:
                continue
            diff_parts.append(f"diff --git a/{filename} b/{filename}")
            diff_parts.append(patch)

        scoped_diff = "\n".join(diff_parts)
        line_scope = _valid_diff_lines(scoped_diff) if scoped_diff else {}
        return changed_paths, line_scope, changed_file_models, scoped_diff

    async def post_review(
        self,
        repo_full_name: str,
        pr_number: int,
        review_result: ReviewResult,
        diff: str = "",
    ) -> PostedReviewResult:
        """
        Post a review to a pull request.

        When *diff* is provided, comments are validated against the diff
        before posting.  Comments whose line numbers fall outside a diff
        hunk are dropped (with a warning) so GitHub doesn't reject the
        entire review with a 422.

        Args:
            repo_full_name: Repository full name (owner/repo)
            pr_number: Pull request number
            review_result: Review result to post
            diff: Full unified diff of the PR (used for line validation)
        """
        # ---- validate comment line numbers against the diff ----
        valid_comments = list(review_result.comments)
        dropped_comments: list[DroppedReviewComment] = []
        if diff and review_result.comments:
            valid_lines = _valid_diff_lines(diff)
            valid_comments = []
            for comment in review_result.comments:
                file_lines = valid_lines.get(comment.path)
                if file_lines is None:
                    dropped_comments.append(
                        DroppedReviewComment(comment=comment, reason="file_not_in_diff")
                    )
                    logger.warning(
                        "Dropped review finding: reason=file_not_in_diff repo=%s pr=%s "
                        "path=%s line=%s severity=%s category=%s body_preview=%r",
                        repo_full_name,
                        pr_number,
                        comment.path,
                        comment.line,
                        _enum_value(comment.severity),
                        _enum_value(comment.category),
                        comment.body[:160],
                    )
                    continue
                if comment.line not in file_lines:
                    # Try to snap to the nearest valid line in the same file
                    nearest = min(file_lines, key=lambda ln: abs(ln - comment.line), default=None)
                    if nearest is not None and abs(nearest - comment.line) <= 5:
                        logger.info(
                            "Snapping comment line %s:%d → %d (nearest in diff)",
                            comment.path,
                            comment.line,
                            nearest,
                        )
                        # ReviewComment is a Pydantic model; create a copy
                        comment = comment.model_copy(update={"line": nearest})
                        valid_comments.append(comment)
                    else:
                        dropped_comments.append(
                            DroppedReviewComment(
                                comment=comment,
                                reason="line_not_in_diff",
                                nearest_valid_line=nearest,
                            )
                        )
                        logger.warning(
                            "Dropped review finding: reason=line_not_in_diff repo=%s pr=%s "
                            "path=%s line=%s nearest_valid_line=%s severity=%s category=%s "
                            "body_preview=%r",
                            repo_full_name,
                            pr_number,
                            comment.path,
                            comment.line,
                            nearest,
                            _enum_value(comment.severity),
                            _enum_value(comment.category),
                            comment.body[:160],
                        )
                    continue
                valid_comments.append(comment)

            dropped = len(review_result.comments) - len(valid_comments)
            if dropped:
                logger.warning(
                    "Dropped %d/%d review finding(s) with invalid diff lines for %s#%s",
                    dropped,
                    len(review_result.comments),
                    repo_full_name,
                    pr_number,
                )

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
                    "body": f"**[{comment.severity.value}] {comment.category.value}** - {comment.body}",
                }
                for comment in valid_comments
            ],
        }

        # Post review
        review_url = f"{self.base_url}/repos/{repo_full_name}/pulls/{pr_number}/reviews"

        try:
            response = await self._http.post(
                review_url, headers=self._get_headers(), json=review_payload
            )
            response.raise_for_status()
            logger.info(f"Successfully posted review with {len(valid_comments)} inline comments")
            return PostedReviewResult(
                attempted=len(review_result.comments),
                posted=len(valid_comments),
                dropped=dropped_comments,
                github_rejected=False,
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 422:
                # Validation should have prevented this, but if GitHub
                # still rejects the review, log and move on rather than
                # falling back to issue comments (which can't be resolved
                # and break dedup).
                logger.error(
                    "GitHub rejected review despite line validation (422). " "Error: %s",
                    e.response.text,
                )
                return PostedReviewResult(
                    attempted=len(review_result.comments),
                    posted=0,
                    dropped=dropped_comments,
                    github_rejected=True,
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
        comment_url = f"{self.base_url}/repos/{repo_full_name}/issues/{pr_number}/comments"
        response = await self._http.post(
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
        comment_url = f"{self.base_url}/repos/{repo_full_name}/issues/comments/{comment_id}"
        response = await self._http.patch(
            comment_url,
            headers=self._get_headers(),
            json={"body": comment},
        )
        response.raise_for_status()

    async def reply_to_review_comment(
        self,
        repo_full_name: str,
        pr_number: int,
        review_comment_id: int,
        comment: str,
    ) -> bool:
        """
        Reply to an existing review comment thread.

        Args:
            repo_full_name: Repository full name (owner/repo)
            pr_number: Pull request number
            review_comment_id: ID of the review comment to reply to
            comment: Comment body

        Returns:
            True if reply was successful, False if comment is outdated (404)
        """
        reply_url = f"{self.base_url}/repos/{repo_full_name}/pulls/{pr_number}/comments/{review_comment_id}/replies"
        response = await self._http.post(
            reply_url,
            headers=self._get_headers(),
            json={"body": comment},
        )
        if response.status_code == 404:
            logger.warning(
                f"Cannot reply to comment {review_comment_id} on PR #{pr_number} - "
                f"GitHub returned 404 (comment may be outdated or deleted)"
            )
            return False
        response.raise_for_status()
        return True

    async def resolve_review_thread(self, thread_node_id: str) -> bool:
        """Resolve a pull request review thread via GraphQL mutation.

        Args:
            thread_node_id: The GraphQL node ID of the thread (PullRequestReviewThread.id).

        Returns:
            True on success, False on any error (fail-open — a failed resolve is not fatal).
        """
        mutation = """
        mutation($threadId: ID!) {
          resolveReviewThread(input: {threadId: $threadId}) {
            thread { id isResolved }
          }
        }
        """
        try:
            response = await self._http.post(
                "https://api.github.com/graphql",
                headers=self._get_headers(),
                json={"query": mutation, "variables": {"threadId": thread_node_id}},
            )
            response.raise_for_status()
            body = response.json()
            if "errors" in body:
                logger.warning(
                    "GraphQL error resolving thread %s: %s",
                    thread_node_id,
                    body["errors"],
                )
                return False
            return True
        except Exception as exc:
            logger.warning("Failed to resolve thread %s: %s", thread_node_id, exc)
            return False

    async def get_commit_info(self, repo_full_name: str, commit_sha: str) -> dict:
        """
        Fetch information about a specific commit.

        Args:
            repo_full_name: Repository full name (owner/repo)
            commit_sha: Commit SHA

        Returns:
            Dict with commit info including parents, message, and files changed
        """
        url = f"{self.base_url}/repos/{repo_full_name}/commits/{commit_sha}"
        response = await self._http.get(url, headers=self._get_headers())
        response.raise_for_status()
        return response.json()

    async def _commit_is_ancestor_of_branch(
        self, repo_full_name: str, commit_sha: str, branch: str
    ) -> bool:
        """Return True if commit_sha is an ancestor of (or identical to) branch HEAD.

        Uses the GitHub compare API: compare/{commit}...{branch} returns
        status "ahead" when branch is ahead of commit (commit is an ancestor)
        or "identical" when they are the same commit.
        """
        url = f"{self.base_url}/repos/{repo_full_name}/compare/{commit_sha}...{branch}"
        response = await self._http.get(url, headers=self._get_headers())
        if response.status_code != 200:
            logger.warning(
                "compare API returned %d for %s...%s in %s; treating as non-ancestor",
                response.status_code,
                commit_sha,
                branch,
                repo_full_name,
            )
            return False
        return response.json().get("status") in ("ahead", "identical")

    async def is_merge_or_sync_commit(
        self, repo_full_name: str, commit_sha: str, base_branch: str
    ) -> tuple[bool, str]:
        """
        Check if a commit is a merge/sync commit that doesn't warrant a new review.

        A push is a sync-with-base when the HEAD commit is a merge commit (2+
        parents) and one of those parents is an ancestor of the base branch —
        meaning the developer merged the base branch into their feature branch.

        Detection uses the GitHub compare API rather than commit message pattern
        matching or file-count heuristics, so it works regardless of message
        wording, author tooling, or how many files changed from upstream.

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

            if len(parents) < 2:
                return False, ""

            for parent in parents:
                parent_sha = parent.get("sha", "")
                if not parent_sha:
                    continue
                if await self._commit_is_ancestor_of_branch(
                    repo_full_name, parent_sha, base_branch
                ):
                    return (
                        True,
                        f"merge commit syncing {base_branch} into feature branch "
                        f"(parent {parent_sha[:7]} is an ancestor of {base_branch})",
                    )

            return False, ""

        except Exception as e:
            logger.warning(
                "Failed to determine merge/sync status for %s in %s: %s",
                commit_sha,
                repo_full_name,
                e,
            )
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
        url = f"{self.base_url}/repos/{repo_full_name}/contents/{path}"
        params = {}
        if ref:
            params["ref"] = ref

        try:
            response = await self._http.get(url, headers=self._get_headers(), params=params)

            if response.status_code == 404:
                logger.debug(f"File not found: {repo_full_name}/{path}")
                return None

            response.raise_for_status()
            data = response.json()

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
        url = f"{self.base_url}/repos/{repo_full_name}/contents/{path}"
        params = {}
        if ref:
            params["ref"] = ref

        try:
            response = await self._http.get(url, headers=self._get_headers(), params=params)

            if response.status_code == 404:
                return []

            response.raise_for_status()
            data = response.json()

            if isinstance(data, list):
                return [item["name"] for item in data if item.get("type") == "file"]

            return []

        except httpx.HTTPStatusError:
            return []

    async def fetch_resolved_thread_ids(
        self, repo_full_name: str, pr_number: int
    ) -> tuple[set[int], set[int], dict[int, str]]:
        """Fetch resolved and outdated root comment database IDs for review threads.

        Uses the GraphQL API because the REST API does not expose the
        ``isResolved`` or ``isOutdated`` state of review threads.

        Returns:
            Tuple of (resolved_ids, outdated_ids, node_id_map).  On error returns
            empty sets/dict so callers degrade gracefully (fail-open).
        """
        owner, repo = repo_full_name.split("/", 1)
        query = """
        query($owner: String!, $repo: String!, $pr: Int!, $cursor: String) {
          repository(owner: $owner, name: $repo) {
            pullRequest(number: $pr) {
              reviewThreads(first: 100, after: $cursor) {
                pageInfo { hasNextPage endCursor }
                nodes {
                  id
                  isResolved
                  isOutdated
                  comments(first: 1) {
                    nodes { databaseId }
                  }
                }
              }
            }
          }
        }
        """

        resolved_ids: set[int] = set()
        outdated_ids: set[int] = set()
        node_id_map: dict[int, str] = {}
        cursor: str | None = None

        try:
            headers = self._get_headers()
            while True:
                variables: dict = {
                    "owner": owner,
                    "repo": repo,
                    "pr": pr_number,
                    "cursor": cursor,
                }
                resp = await self._http.post(
                    "https://api.github.com/graphql",
                    headers=headers,
                    json={"query": query, "variables": variables},
                )
                resp.raise_for_status()
                body = resp.json()

                if "errors" in body:
                    logger.warning(
                        "GraphQL errors fetching resolved threads: %s",
                        body["errors"],
                    )
                    break

                threads_data = (
                    body.get("data", {})
                    .get("repository", {})
                    .get("pullRequest", {})
                    .get("reviewThreads", {})
                )
                for node in threads_data.get("nodes", []):
                    if node is None:
                        continue
                    comments = node.get("comments", {}).get("nodes", [])
                    if not comments or not comments[0].get("databaseId"):
                        continue
                    db_id = comments[0]["databaseId"]
                    thread_node_id = node.get("id")
                    if thread_node_id:
                        node_id_map[db_id] = thread_node_id
                    if node.get("isResolved"):
                        resolved_ids.add(db_id)
                    elif node.get("isOutdated"):
                        outdated_ids.add(db_id)

                page_info = threads_data.get("pageInfo", {})
                if page_info.get("hasNextPage"):
                    cursor = page_info["endCursor"]
                else:
                    break

        except Exception as exc:
            logger.warning(
                "Failed to fetch resolved thread state: %s: %r",
                type(exc).__name__,
                exc,
                exc_info=True,
            )

        return resolved_ids, outdated_ids, node_id_map

    async def fetch_review_comments(self, repo_full_name: str, pr_number: int) -> list[dict]:
        """Fetch all review comments on a PR.

        Args:
            repo_full_name: Repository full name (owner/repo)
            pr_number: Pull request number

        Returns:
            List of raw comment dicts from the GitHub API
        """
        url = f"{self.base_url}/repos/{repo_full_name}/pulls/{pr_number}/comments"
        return await self._fetch_paginated_json(url)

    async def _fetch_paginated_json(self, url: str) -> list[dict]:
        """Fetch all pages from a GitHub REST collection endpoint."""
        results: list[dict] = []
        page = 1
        headers = self._get_headers()

        while True:
            response = await self._http.get(
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
