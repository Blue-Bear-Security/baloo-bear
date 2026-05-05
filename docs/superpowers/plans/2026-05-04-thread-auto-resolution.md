# Thread Auto-Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When Baloo re-reviews a PR and a previously flagged issue is no longer present, automatically reply "Looks like this was addressed in the latest commit. Resolving." and resolve the GitHub thread via GraphQL mutation.

**Architecture:** Extend the FP verifier to run a second concurrent pass over unresolved awaiting threads (reconstructed as ReviewComment objects), using the new diff as context. On an `fp` verdict the thread is replied to and resolved via a new `resolveReviewThread` GraphQL mutation. Thread node IDs are fetched alongside the existing resolved-state query and stored on `DiscussionThread`.

**Tech Stack:** Python 3.10+, pydantic v2, httpx, pytest/pytest-asyncio, GitHub GraphQL API

---

## Task 1: Add `node_id` to `DiscussionThread` and propagate from GraphQL

**Files:**
- Modify: `baloo/github/models.py`
- Modify: `baloo/github/api_client.py` (lines ~111–124 `_apply_resolved_thread_state`, lines ~736–753 GraphQL query)
- Test: `tests/github/test_discussions.py`

### Background

`DiscussionThread` currently tracks `resolved`, `outdated`, `awaiting_response`, `is_baloo_thread`, and `root_comment_id` (the REST comment integer ID). To resolve a thread via GraphQL mutation we need the thread's **GraphQL node ID** (a base64 string like `"PRT_kwDO..."`) — a different identifier from `databaseId`.

The existing `fetch_resolved_thread_ids` query already fetches threads; we just need to add `id` to it and return the mapping.

- [ ] **Step 1: Write the failing test for `node_id` field**

In `tests/github/test_discussions.py`, add:

```python
from baloo.github.models import DiscussionThread
from datetime import datetime, timezone

def test_discussion_thread_has_node_id_field():
    thread = DiscussionThread(
        id=1,
        path="foo.py",
        line=10,
        comments=[],
        last_activity=datetime.now(timezone.utc),
    )
    assert thread.node_id is None

def test_discussion_thread_node_id_can_be_set():
    thread = DiscussionThread(
        id=1,
        path="foo.py",
        line=10,
        comments=[],
        last_activity=datetime.now(timezone.utc),
        node_id="PRT_kwDOBQ",
    )
    assert thread.node_id == "PRT_kwDOBQ"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/github/test_discussions.py::test_discussion_thread_has_node_id_field tests/github/test_discussions.py::test_discussion_thread_node_id_can_be_set -v
```

Expected: `AttributeError` or `ValidationError` — field doesn't exist yet.

- [ ] **Step 3: Add `node_id` to `DiscussionThread`**

In `baloo/github/models.py`, find `DiscussionThread` (currently around line 110) and add one field:

```python
class DiscussionThread(BaseModel):
    """Represents an inline review thread."""

    id: int
    path: str | None
    line: int | None
    comments: list[DiscussionComment]
    is_baloo_thread: bool = False
    awaiting_response: bool = False
    resolved: bool = False
    outdated: bool = False
    last_activity: datetime
    root_comment_id: int | None = None
    node_id: str | None = None  # GraphQL thread node ID for resolveReviewThread mutation
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/github/test_discussions.py::test_discussion_thread_has_node_id_field tests/github/test_discussions.py::test_discussion_thread_node_id_can_be_set -v
```

Expected: PASS.

- [ ] **Step 5: Write failing test for `_apply_resolved_thread_state` writing `node_id`**

In `tests/github/test_discussions.py`, add:

```python
from baloo.github.api_client import _apply_resolved_thread_state

def _make_thread(root_comment_id: int) -> DiscussionThread:
    return DiscussionThread(
        id=root_comment_id,
        path="foo.py",
        line=1,
        comments=[],
        last_activity=datetime.now(timezone.utc),
        root_comment_id=root_comment_id,
    )

def test_apply_resolved_thread_state_writes_node_id():
    thread = _make_thread(root_comment_id=42)
    node_id_map = {42: "PRT_kwDOBQ"}
    _apply_resolved_thread_state(
        [thread],
        resolved_ids=set(),
        outdated_ids=None,
        thread_node_ids=node_id_map,
    )
    assert thread.node_id == "PRT_kwDOBQ"

def test_apply_resolved_thread_state_node_id_missing_from_map():
    thread = _make_thread(root_comment_id=99)
    _apply_resolved_thread_state(
        [thread],
        resolved_ids=set(),
        thread_node_ids={},
    )
    assert thread.node_id is None

def test_apply_resolved_thread_state_existing_behaviour_preserved():
    """Resolved flag still gets set correctly alongside node_id."""
    thread = _make_thread(root_comment_id=7)
    _apply_resolved_thread_state(
        [thread],
        resolved_ids={7},
        thread_node_ids={7: "PRT_abc"},
    )
    assert thread.resolved is True
    assert thread.node_id == "PRT_abc"
```

- [ ] **Step 6: Run tests to confirm they fail**

```bash
uv run pytest tests/github/test_discussions.py::test_apply_resolved_thread_state_writes_node_id tests/github/test_discussions.py::test_apply_resolved_thread_state_node_id_missing_from_map tests/github/test_discussions.py::test_apply_resolved_thread_state_existing_behaviour_preserved -v
```

Expected: `TypeError` — `_apply_resolved_thread_state` doesn't accept `thread_node_ids` yet.

- [ ] **Step 7: Extend `_apply_resolved_thread_state` to accept and write `node_id`**

In `baloo/github/api_client.py`, update `_apply_resolved_thread_state` (around line 111):

```python
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
```

- [ ] **Step 8: Run tests to confirm they pass**

```bash
uv run pytest tests/github/test_discussions.py -v
```

Expected: all pass.

- [ ] **Step 9: Update GraphQL query to fetch thread node ID**

In `baloo/github/api_client.py`, find `fetch_resolved_thread_ids` (around line 736). Update:
1. The query string — add `id` on the thread node
2. The return type — add `dict[int, str]` third element
3. The parsing loop — populate a `node_id_map`
4. The call site in `get_pr_context` — unpack the third value and pass to `_apply_resolved_thread_state`

Change the query from:
```python
        query = """
        query($owner: String!, $repo: String!, $pr: Int!, $cursor: String) {
          repository(owner: $owner, name: $repo) {
            pullRequest(number: $pr) {
              reviewThreads(first: 100, after: $cursor) {
                pageInfo { hasNextPage endCursor }
                nodes {
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
```

To:
```python
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
```

Change the return type annotation from `tuple[set[int], set[int]]` to `tuple[set[int], set[int], dict[int, str]]`.

Add `node_id_map: dict[int, str] = {}` after the `outdated_ids` declaration. In the loop that processes nodes:

```python
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
```

Change the return statement from `return resolved_ids, outdated_ids` to `return resolved_ids, outdated_ids, node_id_map`.

In the `except` block at the end of the function, change the return from `return set(), set()` to `return set(), set(), {}`.

- [ ] **Step 10: Update `get_pr_context` call site**

In `get_pr_context` (around line 236), change:

```python
            resolved_ids, outdated_ids = await self.fetch_resolved_thread_ids(
                repo_full_name, pr_number
            )
            _apply_resolved_thread_state(discussion_threads, resolved_ids, outdated_ids)
```

To:

```python
            resolved_ids, outdated_ids, thread_node_ids = await self.fetch_resolved_thread_ids(
                repo_full_name, pr_number
            )
            _apply_resolved_thread_state(
                discussion_threads, resolved_ids, outdated_ids, thread_node_ids
            )
```

- [ ] **Step 11: Run full test suite**

```bash
uv run pytest tests/ -q
```

Expected: all existing tests pass (the new third return value is ignored by any existing callers that only unpack two values — but check for `ValueError: too many values to unpack` if any test mocks this function).

- [ ] **Step 12: Commit**

```bash
git add baloo/github/models.py baloo/github/api_client.py tests/github/test_discussions.py
git commit -m "feat: add node_id to DiscussionThread and fetch via GraphQL"
```

---

## Task 2: Add `resolve_review_thread` GraphQL mutation

**Files:**
- Modify: `baloo/github/api_client.py`
- Test: `tests/github/test_api_client_resolve.py` (new file)

### Background

GitHub's GraphQL API exposes `resolveReviewThread(input: {threadId: ID!})`. The `threadId` must be the thread's GraphQL node ID (the `id` field we now store as `DiscussionThread.node_id`). There is no REST equivalent.

- [ ] **Step 1: Write the failing test**

Create `tests/github/test_api_client_resolve.py`:

```python
"""Tests for resolve_review_thread GraphQL mutation."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from baloo.github.api_client import GitHubAPIClient


@pytest.fixture
def client():
    with patch("baloo.github.api_client.get_installation_token", return_value="tok"):
        return GitHubAPIClient(installation_id=1)


@pytest.mark.asyncio
async def test_resolve_review_thread_success(client):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "data": {"resolveReviewThread": {"thread": {"id": "PRT_x", "isResolved": True}}}
    }

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_http

        result = await client.resolve_review_thread("PRT_x")

    assert result is True
    call_kwargs = mock_http.post.call_args
    body = call_kwargs[1]["json"]
    assert "resolveReviewThread" in body["query"]
    assert body["variables"]["threadId"] == "PRT_x"


@pytest.mark.asyncio
async def test_resolve_review_thread_graphql_error_returns_false(client):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"errors": [{"message": "not found"}]}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_http

        result = await client.resolve_review_thread("PRT_bad")

    assert result is False


@pytest.mark.asyncio
async def test_resolve_review_thread_http_exception_returns_false(client):
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(side_effect=Exception("network error"))
        mock_client_cls.return_value = mock_http

        result = await client.resolve_review_thread("PRT_x")

    assert result is False
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/github/test_api_client_resolve.py -v
```

Expected: `AttributeError: 'GitHubAPIClient' object has no attribute 'resolve_review_thread'`

- [ ] **Step 3: Implement `resolve_review_thread`**

In `baloo/github/api_client.py`, add after the `reply_to_review_comment` method (around line 570):

```python
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
            async with httpx.AsyncClient() as client:
                response = await client.post(
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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/github/test_api_client_resolve.py -v
```

Expected: all 3 pass.

- [ ] **Step 5: Run full suite**

```bash
uv run pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add baloo/github/api_client.py tests/github/test_api_client_resolve.py
git commit -m "feat: add resolve_review_thread GraphQL mutation"
```

---

## Task 3: `_comment_from_thread` helper

**Files:**
- Modify: `baloo/github/webhook_handler.py`
- Test: `tests/github/test_webhook_handler.py` (add to existing file)

### Background

The FP verifier operates on `ReviewComment` objects. Awaiting threads need to be reconstructed into `ReviewComment` to be passed through. The Baloo comment format is:

```
**[HIGH] Security** - **Title**
**Category:** Security
**Severity:** HIGH

Body...
```

We parse severity from the `[SEVERITY]` bracket and category from the word immediately after it.

- [ ] **Step 1: Write the failing tests**

In `tests/github/test_webhook_handler.py` (or create a new `tests/github/test_comment_from_thread.py` if the existing file is very large — check first), add:

```python
from datetime import datetime, timezone
from baloo.github.models import DiscussionComment, DiscussionThread
from baloo.github.webhook_handler import _comment_from_thread
from baloo.github.models import ReviewSeverity, FindingCategory


def _make_thread(body: str, path: str = "app.py", line: int = 42) -> DiscussionThread:
    comment = DiscussionComment(
        id=1,
        author="baloo-code-reviewer[bot]",
        body=body,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        source="review_comment",
        is_baloo=True,
        path=path,
        line=line,
    )
    return DiscussionThread(
        id=100,
        path=path,
        line=line,
        comments=[comment],
        is_baloo_thread=True,
        awaiting_response=True,
        last_activity=datetime.now(timezone.utc),
        root_comment_id=1,
        node_id="PRT_kwDOBQ",
    )


def test_comment_from_thread_extracts_path_and_line():
    thread = _make_thread("**[HIGH] Security** - **SQL injection**\n**Category:** Security\n**Severity:** HIGH\n\nBad stuff")
    comment = _comment_from_thread(thread)
    assert comment.path == "app.py"
    assert comment.line == 42


def test_comment_from_thread_extracts_severity_high():
    thread = _make_thread("**[HIGH] Security** - **Title**\n**Category:** Security\n**Severity:** HIGH\n\nBody")
    comment = _comment_from_thread(thread)
    assert comment.severity == ReviewSeverity.HIGH


def test_comment_from_thread_extracts_severity_critical():
    thread = _make_thread("**[CRITICAL] Bugs** - **Title**\n**Category:** Bugs\n**Severity:** CRITICAL\n\nBody")
    comment = _comment_from_thread(thread)
    assert comment.severity == ReviewSeverity.CRITICAL


def test_comment_from_thread_extracts_category_security():
    thread = _make_thread("**[HIGH] Security** - **Title**\n**Category:** Security\n**Severity:** HIGH\n\nBody")
    comment = _comment_from_thread(thread)
    assert comment.category == FindingCategory.SECURITY


def test_comment_from_thread_defaults_on_unparseable_body():
    thread = _make_thread("Some freeform text with no severity markers")
    comment = _comment_from_thread(thread)
    assert comment.severity == ReviewSeverity.MEDIUM
    assert comment.category == FindingCategory.QUALITY


def test_comment_from_thread_preserves_full_body():
    body = "**[HIGH] Security** - **Title**\n**Category:** Security\n**Severity:** HIGH\n\nDetailed finding text."
    thread = _make_thread(body)
    comment = _comment_from_thread(thread)
    assert comment.body == body
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/github/test_webhook_handler.py -k "test_comment_from_thread" -v
```

Expected: `ImportError` — `_comment_from_thread` not defined yet.

- [ ] **Step 3: Implement `_comment_from_thread`**

In `baloo/github/webhook_handler.py`, add near the other private helpers (after `_extract_issue_signature`, around line 350):

```python
import re as _re

_SEVERITY_RE = _re.compile(r"\*\*\[(\w+)\]\s+\w+\*\*")
_CATEGORY_RE = _re.compile(r"\*\*\[(?:\w+)\]\s+(\w[\w ]*?)\*\*")

_CATEGORY_MAP: dict[str, FindingCategory] = {
    "security": FindingCategory.SECURITY,
    "bugs": FindingCategory.BUGS,
    "silent failures": FindingCategory.SILENT_FAILURES,
    "guidelines": FindingCategory.GUIDELINES,
    "performance": FindingCategory.PERFORMANCE,
    "quality": FindingCategory.QUALITY,
}


def _comment_from_thread(thread: DiscussionThread) -> ReviewComment:
    """Reconstruct a ReviewComment from a Baloo DiscussionThread for re-verification.

    Parses severity and category from the root comment body. Falls back to
    MEDIUM/QUALITY if the body doesn't match the expected format.
    """
    body = thread.comments[0].body if thread.comments else ""

    severity = ReviewSeverity.MEDIUM
    m = _SEVERITY_RE.search(body)
    if m:
        try:
            severity = ReviewSeverity(m.group(1).upper())
        except ValueError:
            pass

    category = FindingCategory.QUALITY
    m2 = _CATEGORY_RE.search(body)
    if m2:
        category = _CATEGORY_MAP.get(m2.group(1).lower().strip(), FindingCategory.QUALITY)

    return ReviewComment(
        path=thread.path or "",
        line=thread.line or 0,
        body=body,
        severity=severity,
        category=category,
    )
```

Also add `FindingCategory` to the imports from `baloo.github.models` at the top of `webhook_handler.py` if not already present.

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/github/test_webhook_handler.py -k "test_comment_from_thread" -v
```

Expected: all pass.

- [ ] **Step 5: Run full suite**

```bash
uv run pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add baloo/github/webhook_handler.py tests/github/test_webhook_handler.py
git commit -m "feat: add _comment_from_thread helper for thread re-verification"
```

---

## Task 4: Thread re-verification pass and resolution actions

**Files:**
- Modify: `baloo/github/webhook_handler.py`
- Test: `tests/github/test_webhook_handler.py`

### Background

After the thread-matching loop, we collect awaiting threads that the review agent didn't re-file. We run these through `FPVerifier.verify()` concurrently with the new-findings pass. For each `fp` verdict we: (1) reply to the thread, (2) call `resolve_review_thread`, (3) subtract from the awaiting count.

The key change to the pipeline in `webhook_handler.py` is in the `_run_pr_review` function (or equivalent), around line 958 where `decision_comments` is assigned. The re-verification pass runs in parallel with the FP pass for new findings using `asyncio.gather`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/github/test_webhook_handler.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

import pytest

from baloo.github.models import (
    DiscussionComment,
    DiscussionThread,
    FileChange,
    PRContext,
    PRDiscussionContext,
    PRMetadata,
    ReviewComment,
    ReviewSeverity,
    FindingCategory,
)
from baloo.processor.fp_verifier import FPVerificationResult, FPRejection, FPStats


def _make_awaiting_thread(root_comment_id: int = 1, node_id: str = "PRT_x") -> DiscussionThread:
    comment = DiscussionComment(
        id=root_comment_id,
        author="baloo-code-reviewer[bot]",
        body="**[HIGH] Security** - **SQL injection**\n**Category:** Security\n**Severity:** HIGH\n\nBad query.",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        source="review_comment",
        is_baloo=True,
        path="app.py",
        line=10,
    )
    return DiscussionThread(
        id=root_comment_id,
        path="app.py",
        line=10,
        comments=[comment],
        is_baloo_thread=True,
        awaiting_response=True,
        last_activity=datetime.now(timezone.utc),
        root_comment_id=root_comment_id,
        node_id=node_id,
    )


def _make_pr_context(awaiting_threads: list[DiscussionThread] | None = None) -> PRContext:
    return PRContext(
        metadata=PRMetadata(
            repo_full_name="org/repo",
            pr_number=1,
            title="Fix stuff",
            description=None,
            author="dev",
            base_branch="main",
            head_branch="fix/it",
            head_sha="abc123",
            files_changed=[FileChange(filename="app.py", status="modified", additions=1, deletions=1, changes=2)],
        ),
        discussion=PRDiscussionContext(
            threads=awaiting_threads or [],
            awaiting_response_count=len(awaiting_threads) if awaiting_threads else 0,
        ),
        diff="diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -10,1 +10,1 @@\n-bad\n+good\n",
    )


@pytest.mark.asyncio
async def test_reverify_threads_fp_verdict_triggers_reply_and_resolve():
    """An fp verdict on an awaiting thread causes reply + resolve."""
    from baloo.github.webhook_handler import _reverify_awaiting_threads

    thread = _make_awaiting_thread()
    pr_context = _make_pr_context(awaiting_threads=[thread])

    fp_result = FPVerificationResult(
        verified=[],
        rejected=[FPRejection(
            comment=ReviewComment(path="app.py", line=10, body="body", severity=ReviewSeverity.HIGH, category=FindingCategory.SECURITY),
            reason="code was fixed",
            model="claude-haiku",
        )],
        stats=FPStats(),
    )

    mock_api = AsyncMock()
    mock_api.reply_to_review_comment = AsyncMock(return_value=True)
    mock_api.resolve_review_thread = AsyncMock(return_value=True)

    with patch("baloo.github.webhook_handler.FPVerifier") as MockVerifier:
        mock_verifier_instance = AsyncMock()
        mock_verifier_instance.verify = AsyncMock(return_value=fp_result)
        MockVerifier.return_value = mock_verifier_instance

        resolved_count = await _reverify_awaiting_threads(
            awaiting_threads=[thread],
            pr_context=pr_context,
            api_client=mock_api,
        )

    assert resolved_count == 1
    mock_api.reply_to_review_comment.assert_called_once_with(
        "org/repo",
        1,  # root_comment_id
        "Looks like this was addressed in the latest commit. Resolving.",
    )
    mock_api.resolve_review_thread.assert_called_once_with("PRT_x")


@pytest.mark.asyncio
async def test_reverify_threads_real_verdict_no_action():
    """A real verdict leaves the thread untouched."""
    from baloo.github.webhook_handler import _reverify_awaiting_threads

    thread = _make_awaiting_thread()
    pr_context = _make_pr_context(awaiting_threads=[thread])

    fp_result = FPVerificationResult(
        verified=[ReviewComment(path="app.py", line=10, body="body", severity=ReviewSeverity.HIGH, category=FindingCategory.SECURITY)],
        rejected=[],
        stats=FPStats(),
    )

    mock_api = AsyncMock()

    with patch("baloo.github.webhook_handler.FPVerifier") as MockVerifier:
        mock_verifier_instance = AsyncMock()
        mock_verifier_instance.verify = AsyncMock(return_value=fp_result)
        MockVerifier.return_value = mock_verifier_instance

        resolved_count = await _reverify_awaiting_threads(
            awaiting_threads=[thread],
            pr_context=pr_context,
            api_client=mock_api,
        )

    assert resolved_count == 0
    mock_api.reply_to_review_comment.assert_not_called()
    mock_api.resolve_review_thread.assert_not_called()


@pytest.mark.asyncio
async def test_reverify_threads_skips_threads_without_node_id():
    """Threads with no node_id are excluded from re-verification."""
    from baloo.github.webhook_handler import _reverify_awaiting_threads

    thread = _make_awaiting_thread(node_id=None)
    thread.node_id = None
    pr_context = _make_pr_context(awaiting_threads=[thread])

    mock_api = AsyncMock()

    with patch("baloo.github.webhook_handler.FPVerifier") as MockVerifier:
        mock_verifier_instance = AsyncMock()
        mock_verifier_instance.verify = AsyncMock(return_value=FPVerificationResult())
        MockVerifier.return_value = mock_verifier_instance

        resolved_count = await _reverify_awaiting_threads(
            awaiting_threads=[thread],
            pr_context=pr_context,
            api_client=mock_api,
        )

    # Verifier called with empty list (thread filtered out)
    call_args = mock_verifier_instance.verify.call_args[0][0]
    assert call_args == []
    assert resolved_count == 0


@pytest.mark.asyncio
async def test_reverify_threads_empty_list_returns_zero():
    """No awaiting threads → no verifier call, returns 0."""
    from baloo.github.webhook_handler import _reverify_awaiting_threads

    pr_context = _make_pr_context()
    mock_api = AsyncMock()

    resolved_count = await _reverify_awaiting_threads(
        awaiting_threads=[],
        pr_context=pr_context,
        api_client=mock_api,
    )

    assert resolved_count == 0
    mock_api.reply_to_review_comment.assert_not_called()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/github/test_webhook_handler.py -k "test_reverify_threads" -v
```

Expected: `ImportError` — `_reverify_awaiting_threads` not defined.

- [ ] **Step 3: Implement `_reverify_awaiting_threads`**

In `baloo/github/webhook_handler.py`, add after `_comment_from_thread` (same area, around line 370):

```python
async def _reverify_awaiting_threads(
    awaiting_threads: list[DiscussionThread],
    pr_context: PRContext,
    api_client,
) -> int:
    """Re-verify awaiting Baloo threads against the new diff.

    For each thread where the LLM says the issue is no longer present (fp verdict),
    post a resolution reply and resolve the GitHub thread.

    Returns:
        Number of threads resolved.
    """
    if not awaiting_threads:
        return 0

    # Only re-verify threads that have a node_id (needed to resolve)
    eligible = [t for t in awaiting_threads if t.node_id]

    if not eligible:
        logger.info("No awaiting threads with node_id — skipping re-verification")
        return 0

    # Reconstruct ReviewComment objects from thread root comments
    comments = [_comment_from_thread(t) for t in eligible]

    verifier = FPVerifier()
    fp_result = await verifier.verify(comments, pr_context)

    # fp_result.rejected = findings the verifier says are no longer present
    resolved_count = 0
    rejected_paths_lines = {(r.comment.path, r.comment.line) for r in fp_result.rejected}

    for thread in eligible:
        if (thread.path, thread.line) not in rejected_paths_lines:
            continue

        logger.info(
            "Thread re-verified as fixed: %s:%s (thread node %s)",
            thread.path,
            thread.line,
            thread.node_id,
        )

        repo = pr_context.repo_full_name
        pr_number = pr_context.pr_number

        # Reply first (best-effort), then resolve
        if thread.root_comment_id is not None:
            await api_client.reply_to_review_comment(
                repo,
                thread.root_comment_id,
                "Looks like this was addressed in the latest commit. Resolving.",
            )

        await api_client.resolve_review_thread(thread.node_id)
        resolved_count += 1

    return resolved_count
```

Add `FPVerifier` to the imports at the top of `webhook_handler.py`:

```python
from baloo.processor.fp_verifier import FPVerifier
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/github/test_webhook_handler.py -k "test_reverify_threads" -v
```

Expected: all 4 pass.

- [ ] **Step 5: Wire `_reverify_awaiting_threads` into the review pipeline**

In `webhook_handler.py`, find the section after the thread-matching loop where `decision_comments` is assigned (around line 958). The awaiting threads that were NOT re-filed are the ones counted as `skipped_duplicates`. We need to collect them.

In the thread-matching loop (around line 948–950), change from:

```python
                if thread.awaiting_response:
                    skipped_duplicates += 1
                    continue
```

To:

```python
                if thread.awaiting_response:
                    skipped_duplicates += 1
                    awaiting_not_refiled.append(thread)
                    continue
```

And add `awaiting_not_refiled: list[DiscussionThread] = []` in the initialisation block near `skipped_duplicates = 0` (around line 897).

After `decision_comments = fresh_comments + [...]` (around line 958), add the concurrent re-verification:

```python
            # Run FP verifier on new findings and re-verification of awaiting threads concurrently
            fp_verifier_task = asyncio.ensure_future(
                fp_verifier.verify(decision_comments, pr_context)
            ) if decision_comments else None

            reverify_task = asyncio.ensure_future(
                _reverify_awaiting_threads(
                    awaiting_not_refiled, pr_context, github_client
                )
            )

            if fp_verifier_task:
                fp_result = await fp_verifier_task
                decision_comments = fp_result.verified
            auto_resolved_count = await reverify_task
```

> **Note:** In the current codebase, the FP verifier pass for new findings is called earlier in the function (before the thread-matching loop) as `fp_result = await fp_verifier.verify(review_result.comments, pr_context)`. Do NOT move that call. Instead, after the thread-matching loop, call `_reverify_awaiting_threads` as a plain `await` (no concurrent wrapper needed since the new-findings FP pass already completed). The `asyncio.ensure_future` pattern shown above is only needed if you restructure to run them truly concurrently — acceptable either way.

Adjust the awaiting count used in the decision block. Find:

```python
            awaiting_threads = pr_context.awaiting_response_threads
```

Change to:

```python
            awaiting_threads = pr_context.awaiting_response_threads - auto_resolved_count
```

Update the summary text for resolved threads. Find where `awaiting_threads` is mentioned in the summary (around line 996):

```python
            if awaiting_threads:
                summary_text += (
                    f"\n\n⏳ {awaiting_threads} Baloo thread(s) remain open from earlier reviews."
                )
```

Add before it:

```python
            if auto_resolved_count:
                summary_text += (
                    f"\n\n✅ Auto-resolved {auto_resolved_count} previously flagged thread(s) "
                    "that look fixed in this commit."
                )
```

- [ ] **Step 6: Run full test suite**

```bash
uv run pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add baloo/github/webhook_handler.py tests/github/test_webhook_handler.py
git commit -m "feat: auto-resolve fixed Baloo threads via FP re-verification"
```

---

## Task 5: End-to-end smoke test and PR

**Files:**
- No new files

- [ ] **Step 1: Run full test suite with coverage**

```bash
uv run pytest tests/ -q --tb=short
```

Expected: all pass, no regressions.

- [ ] **Step 2: Lint**

```bash
uv run ruff check baloo tests
```

Fix any issues found.

- [ ] **Step 3: Format**

```bash
uv run black baloo tests
```

Commit any formatting changes.

- [ ] **Step 4: Push and open PR**

```bash
git push -u origin <branch-name>
gh pr create --title "feat: auto-resolve fixed Baloo threads via LLM re-verification" \
  --body "..."
```

PR description should explain: what was observed (PR #30 stuck in changes_requested with 0 new findings), what was built, how it works, test coverage.
