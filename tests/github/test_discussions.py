"""Tests for GitHub discussion parsing utilities."""

from datetime import datetime, timezone

from baloo.github.discussions import (
    build_discussion_comment,
    build_discussion_digest,
    build_general_discussion,
    build_review_threads,
)
from baloo.github.models import DiscussionComment, DiscussionThread


def test_build_review_threads_groups_by_root():
    """Inline review comments should group into Baloo-aware threads."""
    raw_comments = [
        {
            "id": 10,
            "body": "🐻 Baloo: please add input validation",
            "user": {"login": "baloo-reviewer[bot]"},
            "created_at": "2025-02-14T10:00:00Z",
            "updated_at": "2025-02-14T10:00:00Z",
            "path": "app/api.py",
            "line": 42,
        },
        {
            "id": 11,
            "in_reply_to_id": 10,
            "body": "Fixed and added tests.",
            "user": {"login": "dev-user"},
            "created_at": "2025-02-14T11:00:00Z",
            "updated_at": "2025-02-14T11:00:00Z",
            "path": "app/api.py",
            "line": 42,
        },
    ]

    threads = build_review_threads(raw_comments)
    assert len(threads) == 1

    thread = threads[0]
    assert thread.is_baloo_thread is True
    assert thread.awaiting_response is False
    assert thread.resolved is True  # developer replied "Fixed..."
    assert thread.path == "app/api.py"
    assert thread.line == 42
    assert len(thread.comments) == 2


def test_build_discussion_digest_counts_awaiting_threads():
    """Digest should include awaiting count and recent discussion summary."""
    now = datetime.now(timezone.utc)
    baloo_comment = DiscussionComment(
        id=1,
        author="baloo-reviewer[bot]",
        body="Need more tests.",
        created_at=now,
        updated_at=now,
        source="review_comment",
        is_baloo=True,
        path="core.py",
        line=12,
    )
    author_reply = DiscussionComment(
        id=2,
        author="dev",
        body="Thanks, addressed this.",
        created_at=now,
        updated_at=now,
        source="review_comment",
        is_baloo=False,
        path="core.py",
        line=12,
    )

    awaiting_thread = DiscussionThread(
        id=101,
        path="core.py",
        line=12,
        comments=[baloo_comment],
        is_baloo_thread=True,
        awaiting_response=True,
        resolved=False,
        last_activity=now,
        root_comment_id=101,
    )
    resolved_thread = DiscussionThread(
        id=102,
        path="core.py",
        line=20,
        comments=[baloo_comment, author_reply],
        is_baloo_thread=True,
        awaiting_response=False,
        resolved=True,
        last_activity=now,
        root_comment_id=102,
    )

    digest, awaiting = build_discussion_digest(
        [awaiting_thread, resolved_thread],
        [
            build_discussion_comment(
                {
                    "id": 7,
                    "body": "General question",
                    "created_at": "2025-02-14T10:00:00Z",
                    "updated_at": "2025-02-14T10:00:00Z",
                    "user": {"login": "reviewer"},
                },
                source="issue_comment",
            )
        ],
    )

    assert awaiting == 1
    assert "**Open Baloo threads awaiting response:** 1" in digest
    assert "core.py:12" in digest
    assert "@reviewer" in digest


def test_developer_reply_not_resolved_not_awaiting():
    """A thread where the developer replied (but didn't 'fix') is not resolved and not awaiting."""
    raw_comments = [
        {
            "id": 20,
            "body": "🐻 Baloo: SQL injection risk",
            "user": {"login": "baloo-reviewer[bot]"},
            "created_at": "2025-02-14T10:00:00Z",
            "updated_at": "2025-02-14T10:00:00Z",
            "path": "src/auth.py",
            "line": 42,
        },
        {
            "id": 21,
            "in_reply_to_id": 20,
            "body": "Declined — this is intentional, the input is already sanitized upstream.",
            "user": {"login": "dev-user"},
            "created_at": "2025-02-14T11:00:00Z",
            "updated_at": "2025-02-14T11:00:00Z",
            "path": "src/auth.py",
            "line": 42,
        },
    ]

    threads = build_review_threads(raw_comments)
    assert len(threads) == 1
    thread = threads[0]
    assert thread.is_baloo_thread is True
    assert thread.awaiting_response is False
    # Not resolved — developer responded but didn't use resolution keywords.
    # The webhook handler skips these threads (not re-reviewed).
    assert thread.resolved is False


def test_build_general_discussion_includes_reviews():
    """Review bodies should be surfaced alongside issue comments."""
    issue_comments = [
        {
            "id": 1,
            "body": "Can we add docs?",
            "created_at": "2025-02-14T09:00:00Z",
            "updated_at": "2025-02-14T09:00:00Z",
            "user": {"login": "maintainer"},
        }
    ]
    reviews = [
        {
            "id": 2,
            "body": "Looks great overall.",
            "state": "APPROVED",
            "submitted_at": "2025-02-14T08:00:00Z",
            "html_url": "https://example.com",
            "user": {"login": "lead"},
        }
    ]

    comments = build_general_discussion(issue_comments, reviews)
    assert len(comments) == 2
    assert comments[0].author == "maintainer"  # Newer timestamp first
    assert comments[1].body.startswith("[Approved Review]")
