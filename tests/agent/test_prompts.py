"""Tests for review prompt construction."""

from baloo.agent.prompts import build_review_prompt
from baloo.github.models import FileChange, PRContext, PRDiscussionContext, PRMetadata


def test_ticket_scope_injected_into_review_prompt():
    pr_context = PRContext(
        metadata=PRMetadata(
            repo_full_name="org/repo",
            pr_number=1,
            title="Add auth endpoint",
            description="Implements login flow",
            author="dev",
            base_branch="main",
            head_branch="feat/PER-42-auth",
            head_sha="abc123",
            files_changed=[
                FileChange(
                    filename="auth.py",
                    status="modified",
                    additions=10,
                    deletions=2,
                    changes=12,
                )
            ],
            ticket_scope="# Linear Issue PER-42: Add auth endpoint\n\n## Description\n\nImplement OAuth login.",
        ),
        discussion=PRDiscussionContext(),
        diff="diff --git a/auth.py ...",
    )

    prompt = build_review_prompt(pr_context)

    assert "PER-42" in prompt
    assert "Implement OAuth login" in prompt
    assert "Ticket" in prompt


def test_no_ticket_scope_produces_no_ticket_section():
    pr_context = PRContext(
        metadata=PRMetadata(
            repo_full_name="org/repo",
            pr_number=1,
            title="Fix typo",
            description="",
            author="dev",
            base_branch="main",
            head_branch="fix/typo",
            head_sha="abc123",
            files_changed=[
                FileChange(
                    filename="readme.md",
                    status="modified",
                    additions=1,
                    deletions=1,
                    changes=2,
                )
            ],
        ),
        discussion=PRDiscussionContext(),
        diff="diff",
    )

    prompt = build_review_prompt(pr_context)

    assert "Implement OAuth login" not in prompt
    assert "ticket_scope" not in prompt
