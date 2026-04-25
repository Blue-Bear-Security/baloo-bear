"""Outcome labeler: determines what happened to each finding after PR merge."""

from __future__ import annotations

import logging

import httpx
from sqlalchemy import select

from baloo.config.settings import get_settings
from baloo.db.engine import get_session_factory
from baloo.db.models import Finding, FindingOutcome, Review
from baloo.github.api_client import GitHubAPIClient
from baloo.outcomes.signals import collect_thread_signals, detect_code_change

logger = logging.getLogger(__name__)


def determine_outcome(signals: dict) -> str:
    """Apply priority logic to signals and return an outcome label.

    Priority order:
    1. code_changed_near_line → "actioned"
    2. reply_sentiment == "negative" → "disputed"
    3. developer_replied AND (reply_sentiment == "positive" OR thread_resolved) → "acknowledged"
    4. Otherwise → "ignored"
    """
    if signals.get("code_changed_near_line"):
        return "actioned"

    if signals.get("reply_sentiment") == "negative":
        return "disputed"

    if signals.get("developer_replied") and (
        signals.get("reply_sentiment") == "positive" or signals.get("thread_resolved")
    ):
        return "acknowledged"

    return "ignored"


async def fetch_merge_signals(
    repo_full_name: str, pr_number: int, installation_id: int
) -> tuple[str, list[dict]]:
    """Fetch diff and review threads for a merged PR from GitHub API.

    Returns:
        (diff_text, threads_list) where each thread is a dict with keys:
        path, line, is_resolved, comments: [{author, body, is_baloo}]
    """
    client = GitHubAPIClient(installation_id)
    headers = client._get_headers()

    async with httpx.AsyncClient() as http:
        # Fetch PR diff
        pr_url = f"{client.base_url}/repos/{repo_full_name}/pulls/{pr_number}"
        diff_resp = await http.get(
            pr_url,
            headers={**headers, "Accept": "application/vnd.github.v3.diff"},
        )
        diff_resp.raise_for_status()
        diff_text = diff_resp.text

        # Fetch review comments (paginated)
        comments_url = f"{client.base_url}/repos/{repo_full_name}/pulls/{pr_number}/comments"
        raw_comments = await client._fetch_paginated_json(http, comments_url, headers=headers)

    # Fetch resolved thread IDs via GraphQL
    resolved_ids = await client.fetch_resolved_thread_ids(repo_full_name, pr_number)

    # Group comments into threads by in_reply_to_id
    # Root comments have in_reply_to_id == None
    root_comments: dict[int, dict] = {}  # comment_id -> thread dict
    child_comments: dict[int, list[dict]] = {}  # root_id -> list of child comment dicts

    for c in raw_comments:
        comment_id = c["id"]
        reply_to = c.get("in_reply_to_id")
        login = c.get("user", {}).get("login", "")
        is_baloo = "baloo" in login.lower()
        comment_dict = {
            "author": login,
            "body": c.get("body", ""),
            "is_baloo": is_baloo,
        }

        if reply_to is None:
            # Root comment
            root_comments[comment_id] = {
                "path": c.get("path", ""),
                "line": c.get("original_line") or c.get("line"),
                "is_resolved": comment_id in resolved_ids,
                "comments": [comment_dict],
            }
        else:
            child_comments.setdefault(reply_to, []).append(comment_dict)

    # Attach children to their root threads
    for root_id, thread in root_comments.items():
        if root_id in child_comments:
            thread["comments"].extend(child_comments[root_id])

    threads = list(root_comments.values())
    return diff_text, threads


async def label_pr_outcomes(repo_full_name: str, pr_number: int, installation_id: int) -> None:
    """Label all findings for a merged PR with outcomes.

    1. Query findings from DB
    2. Fetch merge signals (diff + threads)
    3. For each finding, determine outcome and persist
    """
    settings = get_settings()
    session_factory = get_session_factory(settings.database_url)

    async with session_factory() as session:
        # Find all findings for this PR
        stmt = (
            select(Finding)
            .join(Review, Finding.review_id == Review.id)
            .where(Review.repo_full_name == repo_full_name, Review.pr_number == pr_number)
        )
        result = await session.execute(stmt)
        findings = result.scalars().all()

        if not findings:
            logger.info(
                "No findings for %s#%d, skipping outcome labeling",
                repo_full_name,
                pr_number,
            )
            return

        # Check which findings already have outcomes (idempotency)
        existing_stmt = select(FindingOutcome.finding_id).where(
            FindingOutcome.finding_id.in_([f.id for f in findings])
        )
        existing_result = await session.execute(existing_stmt)
        existing_finding_ids = set(existing_result.scalars().all())

        findings_to_label = [f for f in findings if f.id not in existing_finding_ids]
        if not findings_to_label:
            logger.info(
                "All %d findings for %s#%d already labeled, skipping",
                len(findings),
                repo_full_name,
                pr_number,
            )
            return

    # Fetch signals from GitHub (outside DB session)
    diff_text, threads = await fetch_merge_signals(repo_full_name, pr_number, installation_id)

    # Label each finding
    async with session_factory() as session:
        async with session.begin():
            for finding in findings_to_label:
                # Detect code change near the finding
                code_changed = detect_code_change(finding.file_path, finding.line_number, diff_text)

                # Match finding to a thread (±5 line tolerance)
                matched_thread = None
                for t in threads:
                    if t["path"] == finding.file_path:
                        t_line = t.get("line")
                        if (
                            t_line is not None
                            and finding.line_number is not None
                            and abs(t_line - finding.line_number) <= 5
                        ):
                            matched_thread = t
                            break

                # Collect thread signals
                thread_signals = collect_thread_signals(matched_thread)

                # Combine all signals
                signals = {
                    "code_changed_near_line": code_changed,
                    **thread_signals,
                }

                outcome = determine_outcome(signals)

                finding_outcome = FindingOutcome(
                    finding_id=finding.id,
                    review_id=finding.review_id,
                    repo_full_name=repo_full_name,
                    pr_number=pr_number,
                    outcome=outcome,
                    signals=signals,
                )
                session.add(finding_outcome)

            logger.info(
                "Labeled %d findings for %s#%d",
                len(findings_to_label),
                repo_full_name,
                pr_number,
            )
