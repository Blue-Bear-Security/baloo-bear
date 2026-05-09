"""Tests for thread agent prompt building."""

from __future__ import annotations

from datetime import datetime, timezone

from baloo.agent.thread_prompts import (
    THREAD_AGENT_SYSTEM_PROMPT,
    build_thread_prompt,
)
from baloo.github.models import DiscussionComment


def _make_comment(author: str, body: str, is_baloo: bool = False) -> DiscussionComment:
    now = datetime.now(timezone.utc)
    return DiscussionComment(
        id=1,
        author=author,
        body=body,
        created_at=now,
        updated_at=now,
        source="review_comment",
        is_baloo=is_baloo,
    )


def test_system_prompt_contains_classification_instructions():
    assert "acknowledged" in THREAD_AGENT_SYSTEM_PROMPT
    assert "disagreed_valid" in THREAD_AGENT_SYSTEM_PROMPT
    assert "disagreed_invalid" in THREAD_AGENT_SYSTEM_PROMPT
    assert "question" in THREAD_AGENT_SYSTEM_PROMPT
    assert "unclear" in THREAD_AGENT_SYSTEM_PROMPT


def test_build_thread_prompt_includes_thread_history():
    thread_comments = [
        _make_comment("baloo[bot]", "**[HIGH] Security** - SQL injection risk", is_baloo=True),
        _make_comment("alice", "This uses parameterized queries, not string concat"),
    ]
    result = build_thread_prompt(
        thread_comments=thread_comments,
        code_context="def query(user_id):\n    return db.execute(stmt, [user_id])",
        file_path="src/auth.py",
        line_number=42,
    )
    assert "SQL injection risk" in result
    assert "parameterized queries" in result
    assert "src/auth.py" in result
    assert "42" in result


def test_build_thread_prompt_includes_code_context():
    thread_comments = [
        _make_comment("baloo[bot]", "Finding body", is_baloo=True),
        _make_comment("dev", "Why?"),
    ]
    code = "try:\n    result = fetch()\nexcept Exception:\n    pass"
    result = build_thread_prompt(
        thread_comments=thread_comments,
        code_context=code,
        file_path="app/retry.py",
        line_number=10,
    )
    assert "fetch()" in result
    assert "except Exception" in result
