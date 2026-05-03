"""Utilities for parsing and summarizing GitHub PR discussions."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from baloo.github.models import DiscussionComment, DiscussionThread

# Keywords that imply a thread has been addressed/resolved by a human
RESOLUTION_KEYWORDS = (
    "resolved",
    "fixed",
    "addressed",
    "done",
    "updated",
    "thanks, fixed",
    "lgtm",
    "applied",
)


def parse_timestamp(value: str | None) -> datetime:
    """Parse GitHub timestamp strings into timezone-aware datetimes."""
    if not value:
        return datetime.now(timezone.utc)

    if value.endswith("Z"):
        value = value.replace("Z", "+00:00")

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.now(timezone.utc)


def is_baloo_actor(login: str | None, body: str | None = None) -> bool:
    """
    Best-effort heuristic for determining if a comment was authored by Baloo.

    Args:
        login: GitHub login of the author
        body: Comment body text

    Returns:
        True if the comment was likely authored by Baloo
    """
    normalized_login = (login or "").lower()
    normalized_body = (body or "").lower()

    if "baloo" in normalized_login:
        return True

    if normalized_login.endswith("[bot]") and "baloo" in normalized_body:
        return True

    return False


def build_discussion_comment(
    raw_comment: dict,
    source: str,
    *,
    path: str | None = None,
    line: int | None = None,
) -> DiscussionComment:
    """Convert a raw GitHub comment payload into a DiscussionComment model."""
    user = raw_comment.get("user") or {}
    body = raw_comment.get("body") or ""
    login = user.get("login", "unknown")

    return DiscussionComment(
        id=raw_comment.get("id", 0),
        author=login,
        body=body,
        created_at=parse_timestamp(raw_comment.get("created_at")),
        updated_at=parse_timestamp(raw_comment.get("updated_at") or raw_comment.get("created_at")),
        source=source,
        is_baloo=is_baloo_actor(login, body),
        path=path,
        line=line,
        url=raw_comment.get("html_url"),
    )


def build_review_threads(raw_comments: Sequence[dict]) -> list[DiscussionThread]:
    """Group inline review comments into logical threads."""
    threads: dict[int, list[dict]] = {}

    for comment in raw_comments:
        root_id = (
            comment.get("in_reply_to_id") or comment.get("original_comment_id") or comment["id"]
        )
        threads.setdefault(root_id, []).append(comment)

    discussion_threads: list[DiscussionThread] = []

    for root_id, comments in threads.items():
        ordered = sorted(comments, key=lambda c: c.get("created_at", ""))
        discussion_comments = [
            build_discussion_comment(
                c,
                source="review_comment",
                path=c.get("path"),
                line=c.get("line") or c.get("original_line"),
            )
            for c in ordered
        ]

        is_baloo_thread = any(comment.is_baloo for comment in discussion_comments)
        last_comment = discussion_comments[-1]
        awaiting_response = is_baloo_thread and last_comment.is_baloo
        resolved = determine_resolution_state(
            is_baloo_thread, awaiting_response, discussion_comments
        )

        discussion_threads.append(
            DiscussionThread(
                id=root_id,
                path=ordered[0].get("path"),
                line=ordered[0].get("line") or ordered[0].get("original_line"),
                comments=discussion_comments,
                is_baloo_thread=is_baloo_thread,
                awaiting_response=awaiting_response,
                resolved=resolved,
                last_activity=last_comment.updated_at,
                root_comment_id=root_id,
            )
        )

    discussion_threads.sort(key=lambda thread: thread.last_activity, reverse=True)
    return discussion_threads


def determine_resolution_state(
    is_baloo_thread: bool,
    awaiting_response: bool,
    comments: Sequence[DiscussionComment],
) -> bool:
    """Infer whether a thread has been resolved."""
    if not is_baloo_thread:
        return any(_has_resolution_keyword(comment.body) for comment in comments)

    if any(_has_resolution_keyword(comment.body) for comment in comments if not comment.is_baloo):
        return True

    if not awaiting_response and any(not comment.is_baloo for comment in comments):
        # Developer responded, but no explicit resolution keyword
        return False

    return False


def build_general_discussion(
    issue_comments: Sequence[dict],
    reviews: Sequence[dict],
) -> list[DiscussionComment]:
    """
    Create a chronological list of non-inline discussion comments (issue + reviews).
    """
    comments: list[DiscussionComment] = []

    for comment in issue_comments:
        comments.append(build_discussion_comment(comment, source="issue_comment"))

    for review in reviews:
        body = review.get("body") or ""
        if not body.strip():
            continue

        decorated_body = f"[{review.get('state', 'COMMENTED').title()} Review] {body}"
        raw = {
            "id": review.get("id", 0),
            "body": decorated_body,
            "created_at": review.get("submitted_at"),
            "updated_at": review.get("submitted_at"),
            "html_url": review.get("html_url"),
            "user": review.get("user"),
        }
        comments.append(build_discussion_comment(raw, source="review"))

    comments.sort(key=lambda c: c.created_at, reverse=True)
    return comments


def build_discussion_digest(
    review_threads: Sequence[DiscussionThread],
    general_comments: Sequence[DiscussionComment],
    *,
    max_items: int = 5,
) -> tuple[str, int]:
    """
    Create a concise digest summarizing recent discussions.

    Returns:
        Tuple of (digest_text, awaiting_response_count)
    """
    awaiting_count = sum(
        1 for thread in review_threads if thread.is_baloo_thread and thread.awaiting_response
    )

    lines: list[str] = [
        f"**Open Baloo threads awaiting response:** {awaiting_count}",
        "**Recent inline discussions:**",
    ]

    if review_threads:
        for thread in review_threads[:max_items]:
            status = (
                "⏳"
                if thread.awaiting_response
                else ("✅" if thread.resolved else ("⏭️" if thread.outdated else "💬"))
            )
            location = f"{thread.path}:{thread.line}" if thread.path else f"thread #{thread.id}"
            last = thread.comments[-1]
            summary = _summarize_body(last.body)
            lines.append(f"- {status} {location} (last by @{last.author}): {summary}")
    else:
        lines.append("- No inline review threads yet.")

    if general_comments:
        lines.append("**Recent general comments & reviews:**")
        for comment in general_comments[:max_items]:
            summary = _summarize_body(comment.body)
            lines.append(f"- 💬 @{comment.author}: {summary}")

    digest = "\n".join(lines)
    return digest, awaiting_count


def _has_resolution_keyword(body: str | None) -> bool:
    if not body:
        return False
    lower_body = body.lower()
    return any(keyword in lower_body for keyword in RESOLUTION_KEYWORDS)


def _summarize_body(body: str) -> str:
    """Shrink multi-line bodies into a single concise sentence."""
    normalized = " ".join(body.strip().split())
    if len(normalized) <= 140:
        return normalized
    return f"{normalized[:137]}..."
