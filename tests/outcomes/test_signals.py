"""Tests for signal collection functions."""

from baloo.outcomes.signals import classify_sentiment, collect_thread_signals, detect_code_change

# ---------------------------------------------------------------------------
# classify_sentiment
# ---------------------------------------------------------------------------


class TestClassifySentiment:
    def test_none_returns_none(self):
        assert classify_sentiment(None) is None

    def test_empty_string_returns_none(self):
        assert classify_sentiment("") is None

    def test_whitespace_only_returns_none(self):
        assert classify_sentiment("   ") is None

    # Negative keywords
    def test_false_positive_keyword(self):
        assert classify_sentiment("this is a false positive") == "negative"

    def test_intentional_keyword(self):
        assert classify_sentiment("this was intentional") == "negative"

    def test_disagree_keyword(self):
        assert classify_sentiment("I disagree with this finding") == "negative"

    def test_not_a_bug_keyword(self):
        assert classify_sentiment("not a bug, works as designed") == "negative"

    def test_by_design_keyword(self):
        assert classify_sentiment("this behavior is by design") == "negative"

    # Positive keywords
    def test_fixed_keyword(self):
        assert classify_sentiment("fixed in latest commit") == "positive"

    def test_good_catch_keyword(self):
        assert classify_sentiment("good catch, will address") == "positive"

    def test_thanks_keyword(self):
        assert classify_sentiment("thanks for the review") == "positive"

    def test_done_keyword(self):
        assert classify_sentiment("done") == "positive"

    def test_resolved_keyword(self):
        assert classify_sentiment("resolved this issue") == "positive"

    # Neutral
    def test_unmatched_text_returns_neutral(self):
        assert classify_sentiment("I will look into this later") == "neutral"

    def test_plain_text_neutral(self):
        assert classify_sentiment("ok") == "neutral"

    # Priority: negative beats positive
    def test_negative_beats_positive(self):
        # If both negative and positive keywords present, negative wins
        assert classify_sentiment("fixed but actually false positive") == "negative"

    # Case insensitivity
    def test_case_insensitive_negative(self):
        assert classify_sentiment("FALSE POSITIVE") == "negative"

    def test_case_insensitive_positive(self):
        assert classify_sentiment("FIXED in HEAD") == "positive"


# ---------------------------------------------------------------------------
# detect_code_change
# ---------------------------------------------------------------------------

SAMPLE_DIFF = """\
diff --git a/foo/bar.py b/foo/bar.py
--- a/foo/bar.py
+++ b/foo/bar.py
@@ -10,6 +10,7 @@
 context line
 context line
+added line at 12
 context line
 context line
 context line
diff --git a/other.py b/other.py
--- a/other.py
+++ b/other.py
@@ -1,3 +1,4 @@
 ctx
+added line in other at 2
 ctx
 ctx
"""


class TestDetectCodeChange:
    def test_no_diff_returns_false(self):
        assert detect_code_change("foo/bar.py", 12, None) is False

    def test_empty_diff_returns_false(self):
        assert detect_code_change("foo/bar.py", 12, "") is False

    def test_none_line_number_returns_false(self):
        assert detect_code_change("foo/bar.py", None, SAMPLE_DIFF) is False

    def test_changed_line_exact_match(self):
        # Added line lands at new-file line 12 in foo/bar.py
        assert detect_code_change("foo/bar.py", 12, SAMPLE_DIFF) is True

    def test_changed_line_within_5_above(self):
        # line 12 changed; querying line 10 (2 away) should still return True
        assert detect_code_change("foo/bar.py", 10, SAMPLE_DIFF) is True

    def test_changed_line_within_5_below(self):
        # line 12 changed; querying line 15 (3 away) should still return True
        assert detect_code_change("foo/bar.py", 15, SAMPLE_DIFF) is True

    def test_changed_line_just_outside_window(self):
        # line 12 changed; querying line 18 (6 away) should return False
        assert detect_code_change("foo/bar.py", 18, SAMPLE_DIFF) is False

    def test_different_file_returns_false(self):
        # The change is in foo/bar.py, not baz.py
        assert detect_code_change("baz.py", 12, SAMPLE_DIFF) is False

    def test_other_file_change_detected(self):
        # other.py has an addition at new-file line 2
        assert detect_code_change("other.py", 2, SAMPLE_DIFF) is True

    def test_wrong_file_not_confused(self):
        # other.py line 2 changed, but querying foo/bar.py line 2 should be False
        assert detect_code_change("foo/bar.py", 2, SAMPLE_DIFF) is False

    def test_boundary_exactly_5_away(self):
        # line 12 changed; line 7 is exactly 5 away — should return True
        assert detect_code_change("foo/bar.py", 7, SAMPLE_DIFF) is True

    def test_boundary_6_away_returns_false(self):
        # line 12 changed; line 6 is 6 away — should return False
        assert detect_code_change("foo/bar.py", 6, SAMPLE_DIFF) is False


# ---------------------------------------------------------------------------
# collect_thread_signals
# ---------------------------------------------------------------------------


def _baloo_comment(body="Baloo says hi"):
    return {"author": "baloo[bot]", "body": body, "is_baloo": True}


def _dev_comment(body="looks intentional to me"):
    return {"author": "dev_user", "body": body, "is_baloo": False}


class TestCollectThreadSignals:
    def test_none_thread_returns_empty_signals(self):
        result = collect_thread_signals(None)
        assert result == {
            "thread_resolved": False,
            "developer_replied": False,
            "reply_sentiment": None,
            "reply_text": None,
        }

    def test_resolved_thread_no_dev_reply(self):
        thread = {
            "is_resolved": True,
            "comments": [_baloo_comment()],
        }
        result = collect_thread_signals(thread)
        assert result["thread_resolved"] is True
        assert result["developer_replied"] is False
        assert result["reply_sentiment"] is None
        assert result["reply_text"] is None

    def test_unresolved_thread_no_dev_reply(self):
        thread = {
            "is_resolved": False,
            "comments": [_baloo_comment()],
        }
        result = collect_thread_signals(thread)
        assert result["thread_resolved"] is False
        assert result["developer_replied"] is False

    def test_dev_reply_detected(self):
        thread = {
            "is_resolved": False,
            "comments": [_baloo_comment(), _dev_comment("fixed this")],
        }
        result = collect_thread_signals(thread)
        assert result["developer_replied"] is True
        assert result["reply_text"] == "fixed this"
        assert result["reply_sentiment"] == "positive"

    def test_dev_reply_negative_sentiment(self):
        thread = {
            "is_resolved": True,
            "comments": [_baloo_comment(), _dev_comment("this is intentional")],
        }
        result = collect_thread_signals(thread)
        assert result["thread_resolved"] is True
        assert result["developer_replied"] is True
        assert result["reply_sentiment"] == "negative"

    def test_dev_reply_neutral_sentiment(self):
        thread = {
            "is_resolved": False,
            "comments": [_baloo_comment(), _dev_comment("I will look into this")],
        }
        result = collect_thread_signals(thread)
        assert result["reply_sentiment"] == "neutral"

    def test_first_dev_reply_used(self):
        """Only the first non-Baloo comment is used."""
        thread = {
            "is_resolved": False,
            "comments": [
                _baloo_comment(),
                _dev_comment("fixed"),
                _dev_comment("also resolved"),
            ],
        }
        result = collect_thread_signals(thread)
        assert result["reply_text"] == "fixed"

    def test_reply_text_truncated_to_500_chars(self):
        long_body = "x" * 600
        thread = {
            "is_resolved": False,
            "comments": [_baloo_comment(), _dev_comment(long_body)],
        }
        result = collect_thread_signals(thread)
        assert len(result["reply_text"]) == 500

    def test_empty_comments_list(self):
        thread = {"is_resolved": False, "comments": []}
        result = collect_thread_signals(thread)
        assert result["developer_replied"] is False
        assert result["reply_text"] is None

    def test_only_baloo_comments(self):
        thread = {
            "is_resolved": False,
            "comments": [_baloo_comment(), _baloo_comment("follow-up")],
        }
        result = collect_thread_signals(thread)
        assert result["developer_replied"] is False

    def test_dev_comment_before_baloo(self):
        """Dev comment appearing before Baloo comment should still be found."""
        thread = {
            "is_resolved": False,
            "comments": [_dev_comment("done"), _baloo_comment()],
        }
        result = collect_thread_signals(thread)
        assert result["developer_replied"] is True
        assert result["reply_text"] == "done"
