"""Fetch Linear issue content for fidelity analysis and ticket scope."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from baloo.config.settings import settings

logger = logging.getLogger(__name__)

_MIN_TICKET_CHARS = 300
_MIN_TICKET_LINES = 5


@dataclass
class LinearFetchResult:
    content: str | None
    skipped_reason: str | None  # "not_found" | "insufficient_detail" | None


_ISSUE_QUERY = """
query IssueById($id: String!) {
  issue(id: $id) {
    identifier
    title
    description
    url
    team { key name }
    state { name }
    comments(first: 10) {
      nodes {
        body
        createdAt
        user { name displayName }
      }
    }
  }
}
"""


async def fetch_linear_issue_content(ticket_id: str) -> LinearFetchResult:
    """Fetch a Linear issue. Returns LinearFetchResult with content=None and reason if unavailable."""
    if not settings.linear_api_key:
        return LinearFetchResult(content=None, skipped_reason=None)

    body = json.dumps({"query": _ISSUE_QUERY, "variables": {"id": ticket_id}}).encode("utf-8")
    req = request.Request(
        settings.linear_api_url,
        data=body,
        headers={
            "Authorization": settings.linear_api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        payload = await asyncio.to_thread(_post_graphql, req)
    except (error.HTTPError, error.URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("Linear issue fetch failed for %s: %s", ticket_id, exc)
        return LinearFetchResult(content=None, skipped_reason="not_found")

    if payload.get("errors"):
        logger.warning("Linear returned errors for %s: %s", ticket_id, payload["errors"])
        return LinearFetchResult(content=None, skipped_reason="not_found")

    issue = (payload.get("data") or {}).get("issue")
    if not issue:
        logger.info("No Linear issue found for %s", ticket_id)
        return LinearFetchResult(content=None, skipped_reason="not_found")

    if not _is_ticket_sufficient(issue):
        logger.info("Linear ticket %s has insufficient detail for fidelity analysis", ticket_id)
        return LinearFetchResult(content=None, skipped_reason="insufficient_detail")

    return LinearFetchResult(content=_format_issue_as_plan(issue), skipped_reason=None)


def _post_graphql(req: request.Request) -> dict[str, Any]:
    with request.urlopen(req, timeout=30) as res:
        return json.loads(res.read().decode("utf-8"))


def _is_ticket_sufficient(issue: dict[str, Any]) -> bool:
    """Return True if the ticket has enough content for meaningful fidelity analysis."""
    title = issue.get("title") or ""
    description = issue.get("description") or ""
    combined = f"{title}\n{description}"
    return len(combined) >= _MIN_TICKET_CHARS and len(combined.splitlines()) >= _MIN_TICKET_LINES


def _format_issue_as_plan(issue: dict[str, Any]) -> str:
    identifier = issue.get("identifier") or "unknown"
    title = issue.get("title") or ""
    description = issue.get("description") or ""
    url = issue.get("url") or ""
    state = (issue.get("state") or {}).get("name") or ""
    team = (issue.get("team") or {}).get("key") or ""

    parts = [
        f"# Linear Issue {identifier}: {title}",
        "",
        f"- URL: {url}" if url else "",
        f"- Team: {team}" if team else "",
        f"- State: {state}" if state else "",
        "",
        "## Description",
        "",
        description or "(No description)",
    ]

    comments = ((issue.get("comments") or {}).get("nodes") or [])[:10]
    if comments:
        parts.extend(["", "## Recent Comments", ""])
        for comment in comments:
            author = ((comment.get("user") or {}).get("displayName")) or (
                (comment.get("user") or {}).get("name")
            )
            created_at = comment.get("createdAt") or ""
            body = comment.get("body") or ""
            parts.extend(
                [
                    f"### {author or 'Unknown'} {created_at}".strip(),
                    "",
                    body,
                    "",
                ]
            )

    return "\n".join(p for p in parts if p is not None)
