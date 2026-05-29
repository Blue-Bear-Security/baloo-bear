"""Tests for _comment_from_thread helper."""

from datetime import datetime, timezone

from baloo.github.models import (
    DiscussionComment,
    DiscussionThread,
    FindingCategory,
    ReviewSeverity,
)
from baloo.review.orchestrator import _comment_from_thread


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
    thread = _make_thread(
        "**[HIGH] Security** - **SQL injection**\n**Category:** Security\n**Severity:** HIGH\n\nBad stuff"
    )
    comment = _comment_from_thread(thread)
    assert comment.path == "app.py"
    assert comment.line == 42


def test_comment_from_thread_extracts_severity_high():
    thread = _make_thread(
        "**[HIGH] Security** - **Title**\n**Category:** Security\n**Severity:** HIGH\n\nBody"
    )
    comment = _comment_from_thread(thread)
    assert comment.severity == ReviewSeverity.HIGH


def test_comment_from_thread_extracts_severity_critical():
    thread = _make_thread(
        "**[CRITICAL] Bugs** - **Title**\n**Category:** Bugs\n**Severity:** CRITICAL\n\nBody"
    )
    comment = _comment_from_thread(thread)
    assert comment.severity == ReviewSeverity.CRITICAL


def test_comment_from_thread_extracts_category_security():
    thread = _make_thread(
        "**[HIGH] Security** - **Title**\n**Category:** Security\n**Severity:** HIGH\n\nBody"
    )
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
