"""Tests for cyclic review prevention in prompts."""

from datetime import datetime, timezone

from baloo.agent.prompts import _extract_baloo_recommendations, build_pr_review_prompt
from baloo.github.models import DiscussionComment, DiscussionThread


def test_extract_baloo_recommendations_from_threads():
    """Test that Baloo's previous recommendations are extracted from threads."""
    threads = [
        {
            "id": 1,
            "path": "auth/cache.py",
            "line": 57,
            "is_baloo_thread": True,
            "awaiting_response": True,
            "resolved": False,
            "comments": [
                {
                    "id": 101,
                    "author": "baloo-reviewer[bot]",
                    "body": "**[HIGH] Bugs** - **from_dict() bypasses __post_init__ initialization**\n\n**Recommendation:**\nRemove 'cached_at' from the data dict before creating the instance.",
                    "is_baloo": True,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            ],
        }
    ]

    result = _extract_baloo_recommendations(threads)

    assert "auth/cache.py:57" in result
    assert "Awaiting response" in result
    assert "Remove 'cached_at'" in result


def test_extract_baloo_recommendations_skips_non_baloo_threads():
    """Test that non-Baloo threads are ignored."""
    threads = [
        {
            "id": 1,
            "path": "app.py",
            "line": 10,
            "is_baloo_thread": False,
            "awaiting_response": False,
            "resolved": False,
            "comments": [
                {
                    "id": 201,
                    "author": "developer",
                    "body": "This needs fixing",
                    "is_baloo": False,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            ],
        }
    ]

    result = _extract_baloo_recommendations(threads)

    assert result == ""


def test_prompt_includes_previous_baloo_recommendations():
    """Test that the prompt includes previous Baloo recommendations with warnings."""
    pr_context = {
        "title": "Fix auth caching",
        "author": "dev",
        "description": "Addressing Baloo's feedback",
        "base_branch": "main",
        "head_branch": "fix/auth",
        "files_changed": [{"filename": "auth/cache.py"}],
        "changed_file_paths": ["auth/cache.py"],
        "diff": "diff --git a/auth/cache.py",
        "discussion_digest": "**Open Baloo threads awaiting response:** 1",
        "awaiting_discussions": 1,
        "discussion_threads": [
            {
                "id": 1,
                "path": "auth/cache.py",
                "line": 57,
                "is_baloo_thread": True,
                "awaiting_response": True,
                "resolved": False,
                "last_activity": datetime.now(timezone.utc).isoformat(),
                "comments": [
                    {
                        "id": 101,
                        "author": "baloo-reviewer[bot]",
                        "body": "**[HIGH] Bugs** - **from_dict() bypasses __post_init__ initialization**\n\n**Recommendation:**\nRemove 'cached_at' from the data dict before creating the instance.",
                        "is_baloo": True,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                        "source": "review_comment",
                    }
                ],
            }
        ],
    }

    prompt = build_pr_review_prompt(pr_context)

    # Check that previous recommendations section exists
    assert "Previous Baloo Recommendations" in prompt
    assert "auth/cache.py:57" in prompt
    assert "Remove 'cached_at'" in prompt

    # Check that anti-contradiction warnings are present
    assert "DO NOT contradict" in prompt
    assert "DO NOT flip-flop" in prompt
    assert "previously recommended approach A, don't now recommend approach B" in prompt


def test_prompt_without_baloo_threads_no_warnings():
    """Test that prompt doesn't include warnings when there are no Baloo threads."""
    pr_context = {
        "title": "New feature",
        "author": "dev",
        "description": "Fresh PR",
        "base_branch": "main",
        "head_branch": "feature/new",
        "files_changed": [{"filename": "app.py"}],
        "changed_file_paths": ["app.py"],
        "diff": "diff --git a/app.py",
        "discussion_threads": [],
    }

    prompt = build_pr_review_prompt(pr_context)

    # Should not include previous recommendations section
    assert "Previous Baloo Recommendations" not in prompt
    assert "DO NOT contradict" not in prompt


def test_extract_baloo_recommendations_multiple_threads():
    """Test extraction from multiple Baloo threads."""
    threads = [
        {
            "id": 1,
            "path": "auth/cache.py",
            "line": 57,
            "is_baloo_thread": True,
            "awaiting_response": True,
            "resolved": False,
            "comments": [
                {
                    "id": 101,
                    "author": "baloo-reviewer[bot]",
                    "body": "**Recommendation:**\nUse return cls(**data)",
                    "is_baloo": True,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            ],
        },
        {
            "id": 2,
            "path": "auth/models.py",
            "line": 42,
            "is_baloo_thread": True,
            "awaiting_response": False,
            "resolved": False,
            "comments": [
                {
                    "id": 102,
                    "author": "baloo-reviewer[bot]",
                    "body": "**Recommendation:**\nAdd validation for email format",
                    "is_baloo": True,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            ],
        },
    ]

    result = _extract_baloo_recommendations(threads)

    assert "auth/cache.py:57" in result
    assert "auth/models.py:42" in result
    assert "Use return cls(**data)" in result
    assert "Add validation for email format" in result


def test_extract_baloo_recommendations_fallback_without_marker():
    """Test fallback extraction when Recommendation marker is missing."""
    threads = [
        {
            "id": 1,
            "path": "app.py",
            "line": 10,
            "is_baloo_thread": True,
            "awaiting_response": False,
            "resolved": False,
            "comments": [
                {
                    "id": 101,
                    "author": "baloo-reviewer[bot]",
                    "body": "This code has a security vulnerability. Consider using parameterized queries instead of string concatenation.",
                    "is_baloo": True,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            ],
        }
    ]

    result = _extract_baloo_recommendations(threads)

    assert "app.py:10" in result
    assert "security vulnerability" in result
    assert "parameterized queries" in result


def test_extract_baloo_recommendations_from_models():
    """Production discussion models should work the same as dict fixtures."""
    thread = DiscussionThread(
        id=1,
        path="auth/cache.py",
        line=57,
        is_baloo_thread=True,
        awaiting_response=True,
        resolved=False,
        last_activity=datetime.now(timezone.utc),
        comments=[
            DiscussionComment(
                id=101,
                author="baloo-reviewer[bot]",
                body="**Recommendation:**\nRemove 'cached_at' from the data dict before creating the instance.",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                source="review_comment",
                is_baloo=True,
                path="auth/cache.py",
                line=57,
            )
        ],
    )

    result = _extract_baloo_recommendations([thread])

    assert "auth/cache.py:57" in result
    assert "Awaiting response" in result
    assert "Remove 'cached_at'" in result
