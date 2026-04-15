"""Tests for the FP verification pass."""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from baloo.github.models import (
    FileChange,
    PRContext,
    PRDiscussionContext,
    PRMetadata,
    ReviewComment,
)
from baloo.processor.fp_prompts import (
    build_verification_prompt,
    extract_diff_for_file,
)
from baloo.processor.fp_verifier import (
    FPRejection,
    FPVerificationResult,
    FPVerifier,
    _extract_title,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_comment(
    path: str = "src/auth.py",
    line: int = 42,
    severity: str = "HIGH",
    category: str = "Security",
    body: str = "**SQL injection risk**\n**Category:** Security\n**Severity:** HIGH\n\nString concatenation in query.",
) -> ReviewComment:
    return ReviewComment(
        path=path, line=line, body=body, severity=severity, category=category
    )


def _make_pr_context(
    diff: str = "diff --git a/src/auth.py b/src/auth.py\n--- a/src/auth.py\n+++ b/src/auth.py\n@@ -40,3 +40,5 @@\n+    query = f'SELECT * FROM users WHERE id={user_id}'\n",
    repo_full_name: str = "org/repo",
    pr_number: int = 1,
) -> PRContext:
    return PRContext(
        metadata=PRMetadata(
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            title="Test PR",
            author="dev",
            description="test",
            base_branch="main",
            head_branch="feat/test",
            head_sha="abc123",
            files_changed=[
                FileChange(filename="src/auth.py", status="modified", additions=2, deletions=0, changes=2, patch="")
            ],
        ),
        discussion=PRDiscussionContext(),
        diff=diff,
    )


# ---------------------------------------------------------------------------
# Prompt tests
# ---------------------------------------------------------------------------


class TestFPPrompts:
    def test_build_verification_prompt_basic(self):
        comment = _make_comment()
        prompt = build_verification_prompt(comment, diff_context="+ some code")
        assert "src/auth.py" in prompt
        assert "line 42" in prompt
        assert "HIGH" in prompt
        assert "some code" in prompt

    def test_build_verification_prompt_with_file_context(self):
        comment = _make_comment()
        prompt = build_verification_prompt(
            comment, diff_context="+ code", file_context="def foo():\n    pass"
        )
        assert "File context" in prompt
        assert "def foo()" in prompt

    def test_extract_diff_for_file_found(self):
        diff = (
            "diff --git a/src/a.py b/src/a.py\n"
            "--- a/src/a.py\n"
            "+++ b/src/a.py\n"
            "@@ -1,3 +1,4 @@\n"
            "+new line\n"
            "diff --git a/src/b.py b/src/b.py\n"
            "--- a/src/b.py\n"
            "+++ b/src/b.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        result = extract_diff_for_file(diff, "src/a.py")
        assert "src/a.py" in result
        assert "+new line" in result
        assert "src/b.py" not in result

    def test_extract_diff_for_file_not_found(self):
        diff = "diff --git a/src/a.py b/src/a.py\n+line\n"
        result = extract_diff_for_file(diff, "src/missing.py")
        assert result == ""

    def test_extract_diff_for_file_empty_diff(self):
        assert extract_diff_for_file("", "anything.py") == ""

    def test_extract_diff_for_file_suffix_path_not_matched(self):
        # Asking for "lib/auth.py" must not capture "tests/lib/auth.py"
        diff = (
            "diff --git a/tests/lib/auth.py b/tests/lib/auth.py\n"
            "--- a/tests/lib/auth.py\n"
            "+++ b/tests/lib/auth.py\n"
            "@@ -1,1 +1,2 @@\n"
            "+test_line\n"
            "diff --git a/other.py b/other.py\n"
            "+other\n"
        )
        # No real lib/auth.py block exists — should return empty, not the tests/ one
        result = extract_diff_for_file(diff, "lib/auth.py")
        assert result == ""

    def test_extract_diff_for_file_rename_header(self):
        # Rename diffs still use `a/<old> b/<new>`; extracting by the new
        # path should find the block when `b/<path>` appears in the header.
        diff = (
            "diff --git a/old.py b/new.py\n"
            "similarity index 90%\n"
            "rename from old.py\n"
            "rename to new.py\n"
            "--- a/old.py\n"
            "+++ b/new.py\n"
            "@@ -1,1 +1,1 @@\n"
            "+renamed\n"
        )
        result = extract_diff_for_file(diff, "new.py")
        assert "+renamed" in result


# ---------------------------------------------------------------------------
# Verifier tests
# ---------------------------------------------------------------------------


class TestFPVerifier:
    @pytest.fixture(autouse=True)
    def _set_env(self, monkeypatch):
        monkeypatch.setenv("FP_VERIFICATION_ENABLED", "true")
        monkeypatch.setenv("FP_VERIFICATION_MODEL", "haiku")
        monkeypatch.setenv("FP_AUDIT_LOG_PATH", "")

    @pytest.mark.asyncio
    async def test_empty_comments_returns_empty(self):
        verifier = FPVerifier()
        result = await verifier.verify([], _make_pr_context())
        assert result.verified == []
        assert result.rejected == []
        assert result.stats.total_verified == 0

    @pytest.mark.asyncio
    async def test_real_finding_is_kept(self):
        verifier = FPVerifier()
        comment = _make_comment()
        pr_ctx = _make_pr_context()

        mock_result = (
            {"verdict": "real", "reason": "SQL injection is real"},
            {"cost_usd": 0.001, "model": "haiku"},
        )

        with patch.object(verifier, "_verify_single", new_callable=AsyncMock, return_value=(comment, {"verdict": "real", "reason": "SQL injection is real", "cost_usd": 0.001, "model": "haiku"})):
            result = await verifier.verify([comment], pr_ctx)

        assert len(result.verified) == 1
        assert len(result.rejected) == 0
        assert result.stats.kept == 1

    @pytest.mark.asyncio
    async def test_fp_finding_is_rejected(self):
        verifier = FPVerifier()
        comment = _make_comment()
        pr_ctx = _make_pr_context()

        with patch.object(verifier, "_verify_single", new_callable=AsyncMock, return_value=(comment, {"verdict": "fp", "reason": "Uses parameterized query", "cost_usd": 0.001, "model": "haiku"})):
            result = await verifier.verify([comment], pr_ctx)

        assert len(result.verified) == 0
        assert len(result.rejected) == 1
        assert result.rejected[0].reason == "Uses parameterized query"
        assert result.stats.rejected == 1

    @pytest.mark.asyncio
    async def test_verification_error_keeps_finding(self):
        """Fail-open: errors keep the finding, count it under kept, and log errors."""
        verifier = FPVerifier()
        comment = _make_comment()
        pr_ctx = _make_pr_context()

        with patch.object(verifier, "_verify_single", new_callable=AsyncMock, side_effect=RuntimeError("model timeout")):
            result = await verifier.verify([comment], pr_ctx)

        assert len(result.verified) == 1
        assert len(result.rejected) == 0
        assert result.stats.errors == 1
        # Error-retained findings must also count toward `kept` so that
        # len(verified) == stats.kept is always true.
        assert result.stats.kept == 1
        assert len(result.verified) == result.stats.kept

    @pytest.mark.asyncio
    async def test_verification_error_writes_audit_entry(self):
        """Errors must produce an audit entry with verdict='error' (observability)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            audit_path = f.name

        try:
            verifier = FPVerifier()
            verifier.audit_log_path = audit_path
            comment = _make_comment()
            pr_ctx = _make_pr_context()

            with patch.object(verifier, "_verify_single", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
                await verifier.verify([comment], pr_ctx)

            with open(audit_path) as f:
                lines = f.readlines()
            assert len(lines) == 1
            entry = json.loads(lines[0])
            assert entry["verdict"] == "error"
            assert "boom" in entry["reason"]
            assert entry["cost_usd"] == 0.0
        finally:
            os.unlink(audit_path)

    @pytest.mark.asyncio
    async def test_mixed_verdicts(self):
        verifier = FPVerifier()
        c1 = _make_comment(path="a.py", line=10)
        c2 = _make_comment(path="b.py", line=20)
        c3 = _make_comment(path="c.py", line=30)
        pr_ctx = _make_pr_context()

        async def mock_verify(comment, ctx):
            if comment.path == "b.py":
                return comment, {"verdict": "fp", "reason": "not real", "cost_usd": 0.001, "model": "haiku"}
            return comment, {"verdict": "real", "reason": "legit", "cost_usd": 0.001, "model": "haiku"}

        with patch.object(verifier, "_verify_single", side_effect=mock_verify):
            result = await verifier.verify([c1, c2, c3], pr_ctx)

        assert len(result.verified) == 2
        assert len(result.rejected) == 1
        assert result.rejected[0].comment.path == "b.py"

    @pytest.mark.asyncio
    async def test_audit_log_written(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            audit_path = f.name

        try:
            verifier = FPVerifier()
            verifier.audit_log_path = audit_path
            comment = _make_comment()
            pr_ctx = _make_pr_context()

            with patch.object(verifier, "_verify_single", new_callable=AsyncMock, return_value=(comment, {"verdict": "fp", "reason": "false alarm", "cost_usd": 0.0003, "model": "haiku"})):
                await verifier.verify([comment], pr_ctx)

            with open(audit_path) as f:
                lines = f.readlines()
            assert len(lines) == 1
            entry = json.loads(lines[0])
            assert entry["verdict"] == "fp"
            assert entry["reason"] == "false alarm"
            assert entry["repo"] == "org/repo"
            assert entry["pr_number"] == 1
            assert entry["finding"]["file"] == "src/auth.py"
            assert entry["finding"]["line"] == 42
        finally:
            os.unlink(audit_path)


# ---------------------------------------------------------------------------
# Utility tests
# ---------------------------------------------------------------------------


class TestExtractTitle:
    def test_extracts_bold_title(self):
        assert _extract_title("**SQL injection risk**\nmore text") == "SQL injection risk"

    def test_extracts_first_line_fallback(self):
        assert _extract_title("Some issue here\nmore text") == "Some issue here"

    def test_empty_body(self):
        assert _extract_title("") == ""
