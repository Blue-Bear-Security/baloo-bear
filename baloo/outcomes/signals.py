"""Signal collection for finding outcomes."""

from __future__ import annotations

import re

NEGATIVE_KEYWORDS = ["false positive", "intentional", "disagree", "not a bug", "by design"]
POSITIVE_KEYWORDS = ["fixed", "good catch", "thanks", "done", "resolved"]


def classify_sentiment(text: str | None) -> str | None:
    """Classify reply sentiment using keyword matching.

    Returns "positive", "negative", "neutral", or None if no text.
    Negative keywords take priority over positive keywords.
    """
    if not text or not text.strip():
        return None

    lower = text.lower()

    for kw in NEGATIVE_KEYWORDS:
        if kw in lower:
            return "negative"

    for kw in POSITIVE_KEYWORDS:
        if kw in lower:
            return "positive"

    return "neutral"


def detect_code_change(file_path: str, line_number: int | None, diff: str | None) -> bool:
    """Parse unified diff to check if lines within ±5 of line_number were modified.

    Returns True if a '+' line in the diff for the target file lands within 5
    lines of line_number in the new-file numbering.
    """
    if not diff or line_number is None:
        return False

    file_header_re = re.compile(r"^diff --git a/.+ b/(.+)$")
    hunk_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

    current_file: str | None = None
    new_line: int = 0
    in_target_file = False

    for raw_line in diff.splitlines():
        # File header
        m = file_header_re.match(raw_line)
        if m:
            current_file = m.group(1)
            in_target_file = current_file == file_path
            new_line = 0
            continue

        # Skip --- and +++ metadata lines
        if raw_line.startswith("---") or raw_line.startswith("+++"):
            continue

        # Hunk header
        m = hunk_re.match(raw_line)
        if m:
            new_line = int(m.group(1))
            continue

        if not in_target_file:
            continue

        if raw_line.startswith("+"):
            if abs(new_line - line_number) <= 5:
                return True
            new_line += 1
        elif raw_line.startswith("-"):
            # Deleted lines don't advance new-file counter
            pass
        elif raw_line.startswith("\\"):
            # "\ No newline at end of file" — not a real diff line
            pass
        else:
            # Context line
            new_line += 1

    return False


def collect_thread_signals(thread: dict | None) -> dict:
    """Extract signals from a PR review thread.

    Returns dict with keys:
        thread_resolved, developer_replied, reply_sentiment, reply_text
    """
    empty: dict = {
        "thread_resolved": False,
        "developer_replied": False,
        "reply_sentiment": None,
        "reply_text": None,
    }

    if thread is None:
        return empty

    thread_resolved: bool = bool(thread.get("is_resolved", False))
    comments: list[dict] = thread.get("comments", [])

    dev_comment = next((c for c in comments if not c.get("is_baloo", True)), None)

    if dev_comment is None:
        return {**empty, "thread_resolved": thread_resolved}

    reply_text: str = (dev_comment.get("body") or "")[:500]
    reply_sentiment = classify_sentiment(reply_text)

    return {
        "thread_resolved": thread_resolved,
        "developer_replied": True,
        "reply_sentiment": reply_sentiment,
        "reply_text": reply_text,
    }
