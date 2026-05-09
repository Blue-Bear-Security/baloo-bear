"""Tests for prompt helpers."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from baloo.agent.prompts import (
    _is_dependabot_pr,
    _is_security_patch,
    _is_simple_pr,
    build_pr_review_prompt,
)


def test_prompt_includes_discussion_digest():
    """Prior discussion digest should be embedded in the review prompt."""
    pr_context = {
        "title": "Add webhook handler",
        "author": "dev",
        "description": "Implements new logic",
        "base_branch": "main",
        "head_branch": "feature/hook",
        "files_changed": [{"filename": "baloo/github/webhook_handler.py"}],
        "changed_file_paths": ["baloo/github/webhook_handler.py"],
        "diff": "--- a\n+++ b\n@@\n-foo\n+bar",
        "discussion_digest": "**Open Baloo threads awaiting response:** 1",
        "awaiting_discussions": 1,
    }

    prompt = build_pr_review_prompt(pr_context)

    assert "Prior Discussion Context" in prompt
    assert "**Open Baloo threads awaiting response:** 1" in prompt


def test_prompt_includes_awaiting_discussions_count():
    """Test that awaiting discussions count is included in prompt."""
    pr_context = {
        "title": "Fix bug",
        "author": "dev",
        "description": "Bug fix",
        "base_branch": "main",
        "head_branch": "fix/bug",
        "files_changed": [{"filename": "app.py"}],
        "changed_file_paths": ["app.py"],
        "diff": "--- a\n+++ b\n@@\n-old\n+new",
        "discussion_digest": "Some discussion happened",
        "awaiting_discussions": 3,  # Multiple threads awaiting
    }

    prompt = build_pr_review_prompt(pr_context)

    assert "Baloo is still waiting on **3** thread(s)" in prompt


def test_prompt_without_awaiting_discussions():
    """Test prompt when no discussions are awaiting."""
    pr_context = {
        "title": "Add feature",
        "author": "dev",
        "description": "New feature",
        "base_branch": "main",
        "head_branch": "feature/new",
        "files_changed": [{"filename": "feature.py"}],
        "changed_file_paths": ["feature.py"],
        "diff": "--- a\n+++ b\n@@\n-old\n+new",
        "discussion_digest": "Discussion resolved",
        "awaiting_discussions": 0,  # No threads awaiting
    }

    prompt = build_pr_review_prompt(pr_context)

    assert "still waiting" not in prompt


def test_prompt_without_discussion_digest():
    """Test prompt when no discussion digest exists."""
    pr_context = {
        "title": "Update docs",
        "author": "dev",
        "description": "Doc update",
        "base_branch": "main",
        "head_branch": "docs/update",
        "files_changed": [{"filename": "README.md"}],
        "changed_file_paths": ["README.md"],
        "diff": "--- a\n+++ b\n@@\n-old\n+new",
        # No discussion_digest key
    }

    prompt = build_pr_review_prompt(pr_context)

    assert "Prior Discussion Context" not in prompt


def test_is_dependabot_pr_detects_dependabot_author():
    """Test detection via dependabot author."""
    pr = {"author": "dependabot[bot]", "title": "", "description": ""}
    assert _is_dependabot_pr(pr) is True


def test_is_dependabot_pr_detects_dependabot_in_title():
    """Test detection via dependabot in title."""
    pr = {"author": "user", "title": "dependabot update", "description": ""}
    assert _is_dependabot_pr(pr) is True


def test_is_dependabot_pr_detects_bot_with_bump_keyword():
    """Test detection of bot with bump in title and dependency files."""
    pr = {
        "author": "renovate[bot]",
        "title": "Bump package version",
        "description": "",
        "changed_file_paths": ["package.json"],
    }
    assert _is_dependabot_pr(pr) is True


def test_is_dependabot_pr_rejects_bot_with_bump_but_no_dep_files():
    """Test that bots with bump keyword but no dependency files are rejected."""
    pr = {
        "author": "some-bot[bot]",
        "title": "Bump version in docs",
        "description": "",
        "changed_file_paths": ["docs/version.md"],
    }
    assert _is_dependabot_pr(pr) is False


def test_is_dependabot_pr_rejects_unrelated_bot():
    """Test that non-dependency bots are not detected."""
    pr = {"author": "codecov[bot]", "title": "Coverage report updated", "description": ""}
    assert _is_dependabot_pr(pr) is False


def test_is_dependabot_pr_rejects_regular_user():
    """Test that regular users are not detected."""
    pr = {"author": "john-doe", "title": "Update code", "description": ""}
    assert _is_dependabot_pr(pr) is False


def test_is_security_patch_detects_security_in_title():
    """Test detection via security keyword in title."""
    pr = {"title": "Security update for django", "description": ""}
    assert _is_security_patch(pr) is True


def test_is_security_patch_detects_vulnerability_in_description():
    """Test detection via vulnerability keyword in description."""
    pr = {"title": "", "description": "Fixes vulnerability in auth module"}
    assert _is_security_patch(pr) is True


def test_is_security_patch_detects_cve():
    """Test detection via CVE identifier."""
    pr = {"title": "Bump django", "description": "Fixes CVE-2024-1234"}
    assert _is_security_patch(pr) is True


def test_is_security_patch_rejects_regular_pr():
    """Test that non-security PRs are not detected."""
    pr = {"title": "Add new feature", "description": "Implements user dashboard"}
    assert _is_security_patch(pr) is False


def test_security_patch_notice_in_prompt():
    """Test that security patch notice appears in prompt for Dependabot security PR."""
    pr_context = {
        "title": "chore(deps): Bump js-yaml from 4.1.0 to 4.1.1",
        "author": "dependabot[bot]",
        "description": "Security fix for prototype pollution",
        "files_changed": [{"filename": "package-lock.json"}],
        "changed_file_paths": ["package-lock.json"],
        "diff": "...",
    }

    prompt = build_pr_review_prompt(pr_context)

    assert "🔒 SECURITY PATCH DETECTED" in prompt
    assert "OLD version has vulnerability" in prompt
    assert "Do NOT report the upgrade itself as introducing a vulnerability" in prompt
    assert "Default to APPROVE" in prompt


def test_dependabot_notice_in_prompt():
    """Test that Dependabot notice appears for non-security dependency update."""
    pr_context = {
        "title": "Bump package from 1.0 to 1.1",
        "author": "dependabot[bot]",
        "description": "Regular update",
        "files_changed": [{"filename": "requirements.txt"}],
        "changed_file_paths": ["requirements.txt"],
        "diff": "...",
    }

    prompt = build_pr_review_prompt(pr_context)

    assert "🤖 DEPENDABOT PR DETECTED" in prompt
    assert "automated dependency update" in prompt


def test_no_special_notice_for_regular_pr():
    """Test that regular PRs don't get special notices."""
    pr_context = {
        "title": "Add feature",
        "author": "developer",
        "description": "New feature",
        "base_branch": "main",
        "head_branch": "feature/add-feature",
        "files_changed": [{"filename": "app.py"}],
        "changed_file_paths": ["app.py"],
        "diff": "...",
    }

    prompt = build_pr_review_prompt(pr_context)

    assert "🔒 SECURITY PATCH DETECTED" not in prompt
    assert "🤖 DEPENDABOT PR DETECTED" not in prompt


def test_exhaustive_reporting_in_system_prompt():
    """System prompt instructs the model to report all findings in a single pass."""
    from baloo.agent.prompts import REVIEW_SYSTEM_PROMPT

    assert "Exhaustive Reporting" in REVIEW_SYSTEM_PROMPT
    assert "single pass" in REVIEW_SYSTEM_PROMPT
    assert "completeness check" in REVIEW_SYSTEM_PROMPT
    # "balanced" was removed to avoid self-limiting
    assert "balanced" not in REVIEW_SYSTEM_PROMPT


def test_exhaustive_reporting_in_code_review_prompt():
    """Full code review prompt includes completeness check step."""
    pr_context = {
        "title": "Add auth module",
        "author": "dev",
        "description": "New auth",
        "base_branch": "main",
        "head_branch": "feat/auth",
        "files_changed": [{"filename": "auth.py"}],
        "changed_file_paths": ["auth.py"],
        "diff": "--- a\n+++ b\n@@\n-old\n+new",
    }

    prompt = build_pr_review_prompt(pr_context)

    assert "Step 6: Completeness Check" in prompt
    assert 'skip any findings because you already had "enough"' in prompt


def test_yml_files_not_classified_as_simple():
    """PRs with only .yml files should NOT be classified as simple — they need full security review."""
    pr_context = {"changed_file_paths": [".github/workflows/ci.yml"]}
    assert _is_simple_pr(pr_context) is False


def test_yaml_files_not_classified_as_simple():
    """PRs with only .yaml files should NOT be classified as simple."""
    pr_context = {"changed_file_paths": ["kubernetes/deployment.yaml", "helm/values.yaml"]}
    assert _is_simple_pr(pr_context) is False


def test_mixed_yml_and_py_not_classified_as_simple():
    """PRs mixing .yml and .py files should NOT be classified as simple."""
    pr_context = {"changed_file_paths": [".github/workflows/ci.yml", "app.py"]}
    assert _is_simple_pr(pr_context) is False


def test_requirements_txt_still_classified_as_simple():
    """PRs with only requirements.txt should still be classified as simple (regression check)."""
    pr_context = {"changed_file_paths": ["requirements.txt"]}
    assert _is_simple_pr(pr_context) is True


def test_md_files_still_classified_as_simple():
    """PRs with only .md files should still be classified as simple."""
    pr_context = {"changed_file_paths": ["README.md", "docs/guide.md"]}
    assert _is_simple_pr(pr_context) is True


def test_yml_pr_gets_full_review_prompt():
    """A PR with only YAML files must receive the full review prompt (with grep instructions)."""
    pr_context = {
        "title": "Add CI pipeline",
        "author": "dev",
        "description": "Adds GitHub Actions workflow",
        "base_branch": "main",
        "head_branch": "feat/ci",
        "files_changed": [{"filename": ".github/workflows/ci.yml"}],
        "changed_file_paths": [".github/workflows/ci.yml"],
        "diff": "--- a\n+++ b\n@@\n-old\n+new",
    }

    prompt = build_pr_review_prompt(pr_context)

    # Full review prompt has Step 2 grep instructions; simple prompt does not
    assert "Step 2: Search for Patterns" in prompt
    assert "grep" in prompt.lower()


def test_exhaustive_reporting_in_simple_pr_prompt():
    """Simple PR prompt also includes exhaustive reporting instruction."""
    pr_context = {
        "title": "Update deps",
        "author": "dev",
        "description": "Dep update",
        "files_changed": [{"filename": "requirements.txt"}],
        "changed_file_paths": ["requirements.txt"],
        "diff": "--- a\n+++ b\n@@\n-old\n+new",
    }

    prompt = build_pr_review_prompt(pr_context)

    assert "Be exhaustive" in prompt
    assert "completeness check" in prompt


def test_feedback_signals_section_empty():
    """No signals produces empty section."""
    from baloo.agent.prompts import _feedback_signals_section

    assert _feedback_signals_section([]) == ""


def test_feedback_signals_section_formats_signals():
    """Signals are formatted into a prompt section with header."""
    from baloo.agent.prompts import _feedback_signals_section

    signals = [
        MagicMock(
            category="Silent Failures",
            file_glob="app/retry/*.py",
            pattern="except pass in retry loops is intentional",
            developer="alice",
            created_at=datetime(2026, 5, 7, tzinfo=timezone.utc),
        ),
    ]
    result = _feedback_signals_section(signals)
    assert "Team Feedback Signals" in result
    assert "Silent Failures" in result
    assert "app/retry/*.py" in result
    assert "except pass in retry loops" in result
    assert "@alice" in result
    assert "avoid re-flagging" in result
