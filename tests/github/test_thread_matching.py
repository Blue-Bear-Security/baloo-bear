"""Tests for thread matching logic with fuzzy line matching."""

from datetime import datetime, timezone

from baloo.github.models import DiscussionComment, DiscussionThread, ReviewComment
from baloo.github.webhook_handler import (
    _build_thread_lookup,
    _calculate_similarity,
    _extract_issue_signature,
    _match_thread,
    _threads_from_issue_comments,
)


def _make_thread(
    thread_id: int,
    path: str,
    line: int,
    body: str,
    is_baloo: bool = True,
    awaiting: bool = True,
    resolved: bool = False,
) -> DiscussionThread:
    """Helper to create a DiscussionThread for testing."""
    now = datetime.now(timezone.utc)
    comment = DiscussionComment(
        id=thread_id,
        author="baloo-reviewer[bot]" if is_baloo else "developer",
        body=body,
        created_at=now,
        updated_at=now,
        source="review_comment",
        is_baloo=is_baloo,
        path=path,
        line=line,
    )
    return DiscussionThread(
        id=thread_id,
        path=path,
        line=line,
        comments=[comment],
        is_baloo_thread=is_baloo,
        awaiting_response=awaiting,
        resolved=resolved,
        last_activity=now,
        root_comment_id=thread_id,
    )


class TestBuildThreadLookup:
    """Tests for _build_thread_lookup function."""

    def test_groups_threads_by_path(self):
        """Threads should be grouped by file path."""
        threads = [
            _make_thread(1, "file1.py", 10, "Issue A"),
            _make_thread(2, "file1.py", 20, "Issue B"),
            _make_thread(3, "file2.py", 15, "Issue C"),
        ]
        lookup = _build_thread_lookup(threads)

        assert "file1.py" in lookup
        assert "file2.py" in lookup
        assert len(lookup["file1.py"]) == 2
        assert len(lookup["file2.py"]) == 1

    def test_sorts_threads_by_line_number(self):
        """Threads within a file should be sorted by line number."""
        threads = [
            _make_thread(1, "file.py", 50, "Issue A"),
            _make_thread(2, "file.py", 10, "Issue B"),
            _make_thread(3, "file.py", 30, "Issue C"),
        ]
        lookup = _build_thread_lookup(threads)

        lines = [t.line for t in lookup["file.py"]]
        assert lines == [10, 30, 50]

    def test_skips_threads_without_path_or_line(self):
        """Threads without path or line should be excluded."""
        threads = [
            _make_thread(1, "file.py", 10, "Valid"),
            DiscussionThread(
                id=2,
                path=None,
                line=None,
                comments=[],
                is_baloo_thread=True,
                awaiting_response=False,
                resolved=False,
                last_activity=datetime.now(timezone.utc),
            ),
        ]
        lookup = _build_thread_lookup(threads)

        assert len(lookup) == 1
        assert "file.py" in lookup


class TestExtractIssueSignature:
    """Tests for _extract_issue_signature function."""

    def test_extracts_category_and_description(self):
        """Should extract category and description from Baloo format."""
        body = "**[HIGH] Bugs** - Race condition in SSE message handling"
        sig = _extract_issue_signature(body)

        assert "bugs" in sig
        assert "race condition" in sig

    def test_handles_different_severities(self):
        """Should handle all severity levels."""
        for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            body = f"**[{severity}] Security** - SQL injection vulnerability"
            sig = _extract_issue_signature(body)
            assert "security" in sig
            assert "sql injection" in sig

    def test_fallback_for_non_standard_format(self):
        """Should use first 150 chars for non-standard format."""
        body = "This is a regular comment without the Baloo format"
        sig = _extract_issue_signature(body)

        assert sig == body.lower()


class TestCalculateSimilarity:
    """Tests for _calculate_similarity function."""

    def test_identical_strings_have_high_similarity(self):
        """Identical strings should have similarity of 1.0."""
        sig = "bugs:race condition in sse message handling"
        assert _calculate_similarity(sig, sig) == 1.0

    def test_completely_different_strings_have_zero_similarity(self):
        """Completely different strings should have low similarity."""
        sig1 = "security:sql injection vulnerability"
        sig2 = "performance:slow database query"
        similarity = _calculate_similarity(sig1, sig2)
        assert similarity < 0.3

    def test_similar_issues_have_some_overlap(self):
        """Similar issues should have some word overlap when extracted from full bodies."""
        # Use full Baloo comment format to test realistic scenario
        body1 = "**[HIGH] Bugs** - Race condition in SSE message handling req.body passed directly"
        body2 = "**[HIGH] Bugs** - Missing body validation before passing to handlePostMessage"

        sig1 = _extract_issue_signature(body1)
        sig2 = _extract_issue_signature(body2)
        similarity = _calculate_similarity(sig1, sig2)
        # Both share category and some common terms
        assert similarity > 0.05

    def test_empty_strings_return_zero(self):
        """Empty strings should return 0."""
        assert _calculate_similarity("", "test") == 0.0
        assert _calculate_similarity("test", "") == 0.0
        assert _calculate_similarity("", "") == 0.0


class TestMatchThread:
    """Tests for _match_thread function with fuzzy matching."""

    def test_exact_line_match(self):
        """Should match thread on exact same line."""
        thread = _make_thread(1, "file.py", 50, "**[HIGH] Bugs** - Issue description")
        lookup = _build_thread_lookup([thread])

        comment = ReviewComment(
            path="file.py",
            line=50,
            body="**[HIGH] Bugs** - Issue description",
            severity="HIGH",
            category="Bugs",
        )

        matched = _match_thread(lookup, comment)
        assert matched is not None
        assert matched.id == 1

    def test_fuzzy_line_match_within_tolerance(self):
        """Should match thread within LINE_MATCH_TOLERANCE lines."""
        thread = _make_thread(1, "file.py", 50, "**[HIGH] Bugs** - Race condition in handler")
        lookup = _build_thread_lookup([thread])

        # Comment is 3 lines away (within tolerance of 5)
        comment = ReviewComment(
            path="file.py",
            line=53,
            body="**[HIGH] Bugs** - Race condition in handler",
            severity="HIGH",
            category="Bugs",
        )

        matched = _match_thread(lookup, comment)
        assert matched is not None
        assert matched.id == 1

    def test_no_match_outside_tolerance(self):
        """Should not match when line is beyond the loose window."""
        thread = _make_thread(1, "file.py", 50, "**[HIGH] Bugs** - Issue description")
        lookup = _build_thread_lookup([thread])

        # 35 lines away — outside LINE_MATCH_TOLERANCE_LOOSE
        comment = ReviewComment(
            path="file.py",
            line=85,
            body="**[HIGH] Bugs** - Issue description",
            severity="HIGH",
            category="Bugs",
        )

        matched = _match_thread(lookup, comment)
        assert matched is None

    def test_loose_line_match_when_anchor_shifted(self):
        """Same issue after edits can sit many lines away; still dedupe to the thread."""
        thread = _make_thread(1, "file.py", 50, "**[HIGH] Bugs** - Issue description")
        lookup = _build_thread_lookup([thread])

        comment = ReviewComment(
            path="file.py",
            line=62,
            body="**[HIGH] Bugs** - Issue description",
            severity="HIGH",
            category="Bugs",
        )

        matched = _match_thread(lookup, comment)
        assert matched is not None
        assert matched.id == 1

    def test_no_match_different_file(self):
        """Should not match thread in different file."""
        thread = _make_thread(1, "file1.py", 50, "**[HIGH] Bugs** - Issue description")
        lookup = _build_thread_lookup([thread])

        comment = ReviewComment(
            path="file2.py",
            line=50,
            body="**[HIGH] Bugs** - Issue description",
            severity="HIGH",
            category="Bugs",
        )

        matched = _match_thread(lookup, comment)
        assert matched is None

    def test_prefers_exact_line_match_over_fuzzy(self):
        """Should prefer exact line match when multiple threads exist."""
        thread_exact = _make_thread(1, "file.py", 50, "**[HIGH] Bugs** - Exact match issue")
        thread_nearby = _make_thread(2, "file.py", 48, "**[HIGH] Bugs** - Nearby issue")
        lookup = _build_thread_lookup([thread_exact, thread_nearby])

        comment = ReviewComment(
            path="file.py",
            line=50,
            body="**[HIGH] Bugs** - Exact match issue",
            severity="HIGH",
            category="Bugs",
        )

        matched = _match_thread(lookup, comment)
        assert matched is not None
        assert matched.id == 1  # Should match exact, not nearby

    def test_requires_content_similarity_for_fuzzy_match(self):
        """Fuzzy match should require content similarity."""
        thread = _make_thread(1, "file.py", 50, "**[HIGH] Security** - SQL injection vulnerability")
        lookup = _build_thread_lookup([thread])

        # Same line range but completely different issue
        comment = ReviewComment(
            path="file.py",
            line=52,
            body="**[MEDIUM] Performance** - Slow database query",
            severity="MEDIUM",
            category="Performance",
        )

        matched = _match_thread(lookup, comment)
        # Should not match because content is too different
        assert matched is None

    def test_no_match_for_non_baloo_thread(self):
        """Should not match non-Baloo threads."""
        thread = _make_thread(1, "file.py", 50, "Developer comment", is_baloo=False)
        lookup = _build_thread_lookup([thread])

        comment = ReviewComment(
            path="file.py",
            line=50,
            body="**[HIGH] Bugs** - Issue description",
            severity="HIGH",
            category="Bugs",
        )

        matched = _match_thread(lookup, comment)
        assert matched is None

    def test_handles_empty_lookup(self):
        """Should handle empty lookup gracefully."""
        lookup = _build_thread_lookup([])

        comment = ReviewComment(
            path="file.py",
            line=50,
            body="**[HIGH] Bugs** - Issue",
            severity="HIGH",
            category="Bugs",
        )

        matched = _match_thread(lookup, comment)
        assert matched is None

    def test_handles_comment_without_path_or_line(self):
        """Should handle comments without path or line."""
        thread = _make_thread(1, "file.py", 50, "Issue")
        lookup = _build_thread_lookup([thread])

        comment = ReviewComment(
            path="",
            line=0,
            body="General comment",
            severity="LOW",
            category="Quality",
        )

        matched = _match_thread(lookup, comment)
        assert matched is None


class TestRealWorldScenario:
    """Test real-world scenarios from PR #197."""

    def test_detects_duplicate_sse_body_validation_issue(self):
        """
        Scenario from PR #197:
        - Original comment at line 98: "Race condition in SSE message handling"
        - New finding at line 95: "Missing body validation before passing to handlePostMessage"

        These are semantically similar issues about req.body handling and should match.
        """
        original_thread = _make_thread(
            1,
            "backend/services/mcp/src/transport/sse.ts",
            98,
            "**[HIGH] Bugs** - **Race condition in SSE message handling - req.body passed directly**\n"
            "The comment on line 94-95 states 'Express already parsed the JSON body' and passes "
            "`req.body` as the third argument to `handlePostMessage`. However, if Express body "
            "parsing middleware isn't configured globally or the content-type isn't application/json, "
            "req.body will be undefined or a string, causing the SDK to fail or behave unexpectedly.",
        )
        lookup = _build_thread_lookup([original_thread])

        new_comment = ReviewComment(
            path="backend/services/mcp/src/transport/sse.ts",
            line=95,
            body="**[HIGH] Bugs** - **Missing body validation before passing to handlePostMessage**\n"
            "The req.body is passed directly to transport.handlePostMessage without validation. "
            "While Express body-parser middleware is configured, there's no explicit check that "
            "req.body is present and is valid JSON. If the body-parser middleware fails or is "
            "misconfigured, this could cause runtime errors or undefined behavior.",
            severity="HIGH",
            category="Bugs",
        )

        matched = _match_thread(lookup, new_comment)
        # Should match because:
        # 1. Same file
        # 2. Line 95 is within 5 lines of line 98
        # 3. Both are HIGH/Bugs about req.body/handlePostMessage
        assert matched is not None
        assert matched.id == 1


class TestResolvedThreadMatching:
    """Resolved threads must still match so the caller can skip re-flagging."""

    def test_resolved_thread_is_matched(self):
        """A resolved thread should be returned by _match_thread."""
        thread = _make_thread(
            1,
            "file.py",
            50,
            "**[HIGH] Bugs** - Issue description",
            resolved=True,
            awaiting=False,
        )
        lookup = _build_thread_lookup([thread])

        comment = ReviewComment(
            path="file.py",
            line=50,
            body="**[HIGH] Bugs** - Issue description",
            severity="HIGH",
            category="Bugs",
        )

        matched = _match_thread(lookup, comment)
        assert matched is not None
        assert matched.resolved is True

    def test_resolved_thread_matched_with_fuzzy_line(self):
        """Fuzzy line tolerance should still work for resolved threads."""
        thread = _make_thread(
            1,
            "file.py",
            50,
            "**[HIGH] Security** - SQL injection vulnerability",
            resolved=True,
            awaiting=False,
        )
        lookup = _build_thread_lookup([thread])

        comment = ReviewComment(
            path="file.py",
            line=53,
            body="**[HIGH] Security** - SQL injection vulnerability",
            severity="HIGH",
            category="Security",
        )

        matched = _match_thread(lookup, comment)
        assert matched is not None
        assert matched.resolved is True


class TestThreadsFromIssueComments:
    """Tests for _threads_from_issue_comments (422 fallback dedup)."""

    def _make_issue_comment(
        self, comment_id: int, body: str, is_baloo: bool = True
    ) -> DiscussionComment:
        now = datetime.now(timezone.utc)
        return DiscussionComment(
            id=comment_id,
            author="baloo-reviewer[bot]" if is_baloo else "developer",
            body=body,
            created_at=now,
            updated_at=now,
            source="issue_comment",
            is_baloo=is_baloo,
        )

    def test_extracts_path_and_line(self):
        comment = self._make_issue_comment(
            1, "**[HIGH] Bugs** - src/auth.py:42\n\nSQL injection risk."
        )
        threads = _threads_from_issue_comments([comment])
        assert len(threads) == 1
        assert threads[0].path == "src/auth.py"
        assert threads[0].line == 42
        assert threads[0].is_baloo_thread is True
        assert threads[0].awaiting_response is True

    def test_skips_non_baloo_comments(self):
        comment = self._make_issue_comment(
            1, "**[HIGH] Bugs** - src/auth.py:42\n\nIssue.", is_baloo=False
        )
        threads = _threads_from_issue_comments([comment])
        assert threads == []

    def test_skips_comments_without_location(self):
        comment = self._make_issue_comment(1, "🐻 Baloo review completed in 30s. No issues found!")
        threads = _threads_from_issue_comments([comment])
        assert threads == []

    def test_multiple_findings(self):
        comments = [
            self._make_issue_comment(1, "**[CRITICAL] Security** - lib/db.py:10\n\nSQL injection."),
            self._make_issue_comment(2, "**[MEDIUM] Quality** - lib/utils.py:55\n\nDead code."),
        ]
        threads = _threads_from_issue_comments(comments)
        assert len(threads) == 2
        paths = {t.path for t in threads}
        assert paths == {"lib/db.py", "lib/utils.py"}

    def test_matched_by_thread_lookup(self):
        """Synthetic threads should be matchable by _match_thread."""
        comment = self._make_issue_comment(
            1,
            "**[HIGH] Bugs** - src/handler.py:50\n\n"
            "**[HIGH] Bugs** - Race condition in request handling.",
        )
        threads = _threads_from_issue_comments([comment])
        lookup = _build_thread_lookup(threads)

        new_finding = ReviewComment(
            path="src/handler.py",
            line=50,
            body="**[HIGH] Bugs** - Race condition in request handling.",
            severity="HIGH",
            category="Bugs",
        )
        matched = _match_thread(lookup, new_finding)
        assert matched is not None
        assert matched.id == 1

    def test_multi_word_category_silent_failures(self):
        """Regex must handle 'Silent Failures' (space in category name)."""
        comment = self._make_issue_comment(
            1, "**[CRITICAL] Silent Failures** - src/worker.py:88\n\nSwallowed exception."
        )
        threads = _threads_from_issue_comments([comment])
        assert len(threads) == 1
        assert threads[0].path == "src/worker.py"
        assert threads[0].line == 88
