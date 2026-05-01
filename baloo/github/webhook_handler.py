"""FastAPI webhook handler for GitHub events."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from baloo.agent.config import get_agent_options
from baloo.agent.pi_runtime import PIAgentBase
from baloo.config.settings import settings
from baloo.db.engine import close_db, init_db
from baloo.db.service import ReviewCompleteDTO, ReviewService
from baloo.fidelity.fidelity_analyzer import analyze_fidelity
from baloo.fidelity.fidelity_report import (
    ERROR_FIDELITY_SENTINEL,
    MISSING_PLAN_FIDELITY_SENTINEL,
    NO_TICKET_FIDELITY_SENTINEL,
    STATIC_FIDELITY_SENTINELS,
    format_fidelity_report,
)
from baloo.fidelity.models import FidelityResult
from baloo.fidelity.plan_fetcher import fetch_plan_content
from baloo.fidelity.ticket_extractor import extract_ticket_id
from baloo.github.api_client import GitHubAPIClient, PostedReviewResult
from baloo.github.auth import verify_webhook_signature
from baloo.github.models import (
    DiscussionComment,
    DiscussionThread,
    PRContext,
    PullRequestWebhookPayload,
    ReviewComment,
    ReviewResult,
)
from baloo.outcomes.labeler import label_pr_outcomes
from baloo.processor.decision_engine import DecisionEngine
from baloo.processor.findings_filter import FindingsFilter
from baloo.processor.formatter import CommentFormatter
from baloo.processor.severity_router import (
    ReviewSeverity,
    count_by_severity,
    route_findings,
)

logger = logging.getLogger(__name__)

_SYNC_SCOPE_DECIDER_SYSTEM_PROMPT = """You decide synchronize review scope.

Return JSON only:
{
  "mode": "scoped" | "full_pr",
  "reason": "<short reason>"
}

Choose "scoped" when the latest push can be reviewed primarily from before..head delta.
Choose "full_pr" when latest push likely changes behavior broadly enough to re-review the full PR.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize and tear down database."""
    if settings.database_enabled and settings.database_url:
        logger.info("Database enabled, initializing...")
        await init_db(settings.database_url)
    yield
    if settings.database_enabled:
        await close_db()


# Disable docs in production for security
app = FastAPI(
    title="Baloo Code Review Agent",
    docs_url=None if settings.app_environment == "production" else "/docs",
    redoc_url=None if settings.app_environment == "production" else "/redoc",
    openapi_url=None if settings.app_environment == "production" else "/openapi.json",
    lifespan=lifespan,
)

# Mount dashboard if enabled (requires database + credentials)
if (
    settings.dashboard_enabled
    and settings.database_enabled
    and settings.database_url
    and settings.dashboard_username
    and settings.dashboard_password
):
    from baloo.dashboard.router import router as dashboard_router

    app.include_router(dashboard_router)
    _static_dir = Path(__file__).resolve().parent.parent / "dashboard" / "static"
    app.mount("/dashboard-static", StaticFiles(directory=str(_static_dir)), name="dashboard-static")

# Semaphore to limit concurrent reviews (prevent overwhelming the system)
# Initialized lazily on first use to respect settings
review_semaphore = None

# Registry of active review tasks to allow cancellation of redundant reviews
# Map of (repo_full_name, pr_number) -> asyncio.Task
active_reviews: dict[tuple[str, int], asyncio.Task] = {}


def get_review_semaphore() -> asyncio.Semaphore:
    """Get or create the review semaphore with the configured limit."""
    global review_semaphore
    if review_semaphore is None:
        review_semaphore = asyncio.Semaphore(settings.max_concurrent_reviews)
        logger.info(
            f"Initialized review queue with max {settings.max_concurrent_reviews} concurrent reviews"
        )
    return review_semaphore


def cancel_existing_review(repo_full_name: str, pr_number: int) -> None:
    """Cancel any existing review task for the same PR."""
    key = (repo_full_name, pr_number)
    if key in active_reviews:
        task = active_reviews[key]
        if not task.done():
            logger.info(f"Cancelling redundant review for {repo_full_name}#{pr_number}")
            task.cancel()
        del active_reviews[key]


@app.get("/")
async def root() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "baloo"}


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


# ------------------------------------------------------------------
# Thread matching and deduplication helpers
# ------------------------------------------------------------------

# Max lines difference to consider a finding as part of an existing thread
LINE_MATCH_TOLERANCE = 5


def _build_thread_lookup(threads: list[DiscussionThread]) -> dict[str, list[DiscussionThread]]:
    """Build a lookup dictionary for discussion threads grouped by file path."""
    lookup = defaultdict(list)
    for thread in threads:
        if thread.path and thread.line is not None:
            lookup[thread.path].append(thread)

    # Sort threads within each file by line number for faster matching
    for path in lookup:
        lookup[path].sort(key=lambda t: t.line if t.line is not None else 0)

    return lookup


# Regex for the header Baloo writes when falling back to issue comments:
#   **[SEVERITY] Category** - path/to/file.py:42
# Category may contain spaces (e.g. "Silent Failures"), so use [^*]+?
# to match up to the closing **.
_ISSUE_COMMENT_LOCATION_RE = re.compile(
    r"\*\*\[(?:CRITICAL|HIGH|MEDIUM|LOW)\]\s+[^*]+?\*\*\s*-\s*(\S+?):(\d+)"
)


_LEGACY_STATIC_FIDELITY_MARKERS = {
    NO_TICKET_FIDELITY_SENTINEL: ("No ticket ID found",),
    MISSING_PLAN_FIDELITY_SENTINEL: ("No plan file found",),
    ERROR_FIDELITY_SENTINEL: ("Fidelity analysis encountered an error",),
}


def _static_fidelity_sentinel_for_body(body: str) -> str | None:
    """Return the static fidelity report sentinel represented by a comment body."""
    for sentinel in STATIC_FIDELITY_SENTINELS:
        if sentinel in body:
            return sentinel

    if "Fidelity Report" not in body:
        return None

    # Keep one migration path for comments posted before sentinels existed.
    for sentinel, legacy_markers in _LEGACY_STATIC_FIDELITY_MARKERS.items():
        if all(marker in body for marker in legacy_markers):
            return sentinel

    return None


def _has_existing_static_fidelity_report(
    issue_comments: list[DiscussionComment], report_body: str
) -> bool:
    """Check whether Baloo already posted this static fidelity report type."""
    report_sentinel = _static_fidelity_sentinel_for_body(report_body)
    if report_sentinel is None:
        return False

    return any(
        comment.is_baloo and _static_fidelity_sentinel_for_body(comment.body) == report_sentinel
        for comment in issue_comments
    )


def _total_review_cost_usd(review_metadata: dict, fidelity_metadata: dict) -> float:
    """Aggregate all model-call cost components associated with a review."""
    fp_metadata = review_metadata.get("fp_verification") or {}
    if not isinstance(fp_metadata, dict):
        fp_metadata = {}

    return (
        (review_metadata.get("cost_usd") or 0.0)
        + (fidelity_metadata.get("cost_usd") or 0.0)
        + (fp_metadata.get("cost_usd") or 0.0)
    )


def _threads_from_issue_comments(
    issue_comments: list[DiscussionComment],
) -> list[DiscussionThread]:
    """Build synthetic DiscussionThread objects from Baloo issue comments.

    When GitHub rejects inline review comments (422), Baloo falls back to
    posting findings as issue-level comments.  These contain the file path
    and line number in the body (``**[SEV] Cat** - path:line``).  Without
    this conversion the dedup logic cannot see prior findings and will
    re-flag the same issues on every review run.
    """
    threads: list[DiscussionThread] = []
    for comment in issue_comments:
        if not comment.is_baloo:
            continue
        m = _ISSUE_COMMENT_LOCATION_RE.search(comment.body)
        if not m:
            continue
        path = m.group(1)
        try:
            line = int(m.group(2))
        except ValueError:
            continue

        threads.append(
            DiscussionThread(
                id=comment.id,
                path=path,
                line=line,
                comments=[comment],
                is_baloo_thread=True,
                # Issue comments have no thread reply mechanism, so treat
                # them as awaiting response (dedup will skip re-flagging).
                awaiting_response=True,
                resolved=False,
                last_activity=comment.updated_at,
                root_comment_id=comment.id,
            )
        )
    return threads


def _within_changed_line_scope(
    comment: ReviewComment,
    changed_line_scope: dict[str, set[int]],
    *,
    proximity_window: int = 25,
) -> bool:
    """Check whether finding is on/near latest-push changed lines in its file."""
    file_scope = changed_line_scope.get(comment.path)
    if file_scope is None:
        # No line-level scope for this file (e.g. binary/rename without patch):
        # allow file-level scope to decide.
        return True
    if comment.line in file_scope:
        return True
    nearest = min(file_scope, key=lambda ln: abs(ln - comment.line), default=None)
    return nearest is not None and abs(nearest - comment.line) <= proximity_window


async def _decide_synchronize_review_mode(
    *,
    pr_context: PRContext,
    changed_files_changed: list,
    scoped_diff: str,
) -> tuple[str, str]:
    """Ask PI whether synchronize should use scoped or full PR context."""
    options = get_agent_options()
    options.system_prompt = _SYNC_SCOPE_DECIDER_SYSTEM_PROMPT
    options.max_turns = 1
    options.no_tools = True
    options.thinking_level = "minimal"
    decider = PIAgentBase(options)

    changed_files_list = "\n".join(
        f"- {f.filename} (+{f.additions}/-{f.deletions})"
        for f in changed_files_changed[:60]
        if getattr(f, "filename", None)
    )
    prompt = f"""
PR title: {pr_context.title}
PR description (truncated): {(pr_context.description or "")[:800]}
Full PR files changed: {len(pr_context.files_changed)}
Latest push files changed: {len(changed_files_changed)}

Latest push file list:
{changed_files_list or "- (none)"}

Latest push scoped diff (truncated):
{scoped_diff[:12000]}

Full PR diff (truncated):
{pr_context.diff[:12000]}
"""
    try:
        structured, _ = await decider.run_query(prompt)
        if isinstance(structured, dict):
            mode = str(structured.get("mode", "")).strip().lower()
            reason = str(structured.get("reason", "")).strip()
            if mode in {"scoped", "full_pr"}:
                return mode, reason or "LLM scope decision"
    except Exception as exc:
        logger.warning("Scope decider failed, defaulting full_pr: %s", exc)

    return "full_pr", "Scope decision unavailable; defaulting to full PR"


def _extract_issue_signature(body: str) -> str:
    """
    Extract a normalized signature from a Baloo finding body.
    Format: "**[SEVERITY] Category** - Description" -> "category:description"
    """
    # First, handle the bold category part: **[SEVERITY] Category** - Remainder
    match = re.search(r"\*\*\[(?:.*?)\]\s+(.*?)\*\*\s*-\s*(.*)", body, re.DOTALL | re.IGNORECASE)
    if match:
        category = match.group(1).strip().lower()
        remainder = match.group(2).strip().lower()

        # Strip markdown bolding/italics/backticks
        remainder = re.sub(r"[`*_]", "", remainder)

        # Normalize whitespace
        remainder = " ".join(remainder.split())
        return f"{category}:{remainder}"

    # Fallback: normalize the whole body
    return " ".join(body.strip().lower().split())


def _dedupe_similar_findings(comments: list[ReviewComment]) -> tuple[list[ReviewComment], int]:
    """Collapse near-duplicate findings within the same review run."""
    if not comments:
        return comments, 0

    deduped: list[ReviewComment] = []
    seen_keys: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)
    dropped = 0

    for comment in comments:
        signature = _extract_issue_signature(comment.body)
        category = str(
            comment.category.value if hasattr(comment.category, "value") else comment.category
        )
        key = (comment.path, category.lower())
        seen = seen_keys[key]
        is_duplicate = any(
            _calculate_similarity(signature, existing_sig) >= 0.3
            and abs(comment.line - existing_line) <= 5
            for existing_sig, existing_line in seen
        )
        if is_duplicate:
            dropped += 1
            continue

        deduped.append(comment)
        seen.append((signature, comment.line))

    return deduped, dropped


def _calculate_similarity(s1: str, s2: str) -> float:
    """
    Calculate similarity between two issue signatures.
    Uses token-based Jaccard similarity.
    """
    if not s1 or not s2:
        return 0.0

    # Tokenize by non-alphanumeric characters
    def tokenize(s):
        # We include technical keywords that often indicate the same issue
        tokens = re.findall(r"\w+", s.lower())
        return {t for t in tokens if len(t) > 2 or t.isdigit()}

    tokens1 = tokenize(s1)
    tokens2 = tokenize(s2)

    if not tokens1 or not tokens2:
        return 0.0

    intersection = tokens1 & tokens2
    union = tokens1 | tokens2

    sim = len(intersection) / len(union)
    return sim


def _match_thread(
    lookup: dict[str, list[DiscussionThread]], comment: ReviewComment
) -> DiscussionThread | None:
    """
    Find a matching existing thread for a finding using fuzzy line matching
    and content similarity.
    """
    if not comment.path or comment.line is None:
        return None

    threads_in_file = lookup.get(comment.path, [])
    if not threads_in_file:
        return None

    comment_sig = _extract_issue_signature(comment.body)

    best_match = None
    best_similarity = 0.0

    for thread in threads_in_file:
        # 1. Skip non-Baloo threads (but keep resolved ones — the caller
        #    decides whether to post a follow-up or drop the finding).
        if not thread.is_baloo_thread:
            continue

        # 2. Check if line is within tolerance
        line_diff = abs(thread.line - comment.line)
        if line_diff > LINE_MATCH_TOLERANCE:
            continue

        # 3. Check content similarity
        if not thread.comments:
            continue

        thread_sig = _extract_issue_signature(thread.comments[0].body)
        similarity = _calculate_similarity(comment_sig, thread_sig)

        # DEBUG
        # print(f"Comparing line {comment.line} with thread at {thread.line}")
        # print(f"Similarity: {similarity}")
        # print(f"S1: {comment_sig}")
        # print(f"S2: {thread_sig}")

        # 4. If exact line match and very high similarity, it's a definite match
        if line_diff == 0 and similarity > 0.8:
            return thread

        # 5. Otherwise, track the best fuzzy match
        if similarity > best_similarity:
            best_similarity = similarity
            best_match = thread

    # Return best match if it's "similar enough"
    # Threshold 0.2 catches semantically related but differently phrased issues
    return best_match if best_similarity >= 0.2 else None


@app.post("/webhook")
async def handle_webhook(
    request: Request, background_tasks: BackgroundTasks
) -> dict[str, str | int]:
    """
    Handle GitHub webhook events.

    Args:
        request: FastAPI request object
        background_tasks: FastAPI background tasks

    Returns:
        Status response
    """
    # Verify webhook signature
    signature = request.headers.get("X-Hub-Signature-256")
    body = await request.body()

    if not verify_webhook_signature(body, signature):
        logger.warning("Invalid webhook signature")
        raise HTTPException(status_code=403, detail="Invalid signature")

    # Parse event type and payload
    event = request.headers.get("X-GitHub-Event")
    payload = await request.json()

    logger.info(f"Received {event} event")

    # Handle pull_request events
    if event == "pull_request":
        try:
            webhook_payload = PullRequestWebhookPayload(**payload)
            action = webhook_payload.action
            pr_number = webhook_payload.number
            repo_name = webhook_payload.repository.full_name

            # Only process opened, synchronize (new commits), reopened, and ready_for_review actions
            if action in ["opened", "synchronize", "reopened", "ready_for_review"]:
                # Skip draft PRs
                if webhook_payload.pull_request.draft:
                    logger.info(f"Skipping draft PR: {repo_name}#{pr_number} (action: {action})")
                    return {"status": "skipped", "reason": "draft PR"}

                # For synchronize events, check if this is just a merge/sync commit
                head_sha = webhook_payload.pull_request.head.get("sha")
                base_branch = webhook_payload.pull_request.base.get("ref", "main")
                before_sha = payload.get("before")

                if action == "synchronize" and head_sha:
                    github_client = GitHubAPIClient(webhook_payload.installation.id)
                    is_merge, merge_reason = await github_client.is_merge_or_sync_commit(
                        repo_name, head_sha, base_branch
                    )
                    if is_merge:
                        logger.info(f"Skipping review for {repo_name}#{pr_number}: {merge_reason}")
                        return {"status": "skipped", "reason": merge_reason}

                # Check current queue status
                semaphore = get_review_semaphore()
                waiting = settings.max_concurrent_reviews - semaphore._value
                logger.info(
                    f"Queuing review: {repo_name}#{pr_number} (action: {action}) "
                    f"- {waiting} review(s) currently running"
                )

                # Cancel redundant review if one exists
                cancel_existing_review(repo_name, pr_number)

                # Process PR review in background
                task = asyncio.create_task(
                    process_pr_review(
                        webhook_payload.repository.full_name,
                        pr_number,
                        webhook_payload.installation.id,
                        f"pull_request:{action}",
                        True,
                        before_sha if action == "synchronize" else None,
                    )
                )
                active_reviews[(repo_name, pr_number)] = task

                # Add to FastAPI background tasks so it isn't garbage collected early
                background_tasks.add_task(lambda: None)

                return {"status": "queued", "queue_depth": waiting}
            elif action == "closed":
                if webhook_payload.pull_request.merged:
                    logger.info(f"PR merged: {repo_name}#{pr_number} — triggering outcome labeling")
                    task = asyncio.create_task(
                        label_pr_outcomes(repo_name, pr_number, webhook_payload.installation.id)
                    )
                    task.add_done_callback(
                        lambda t: (
                            logger.error("label_pr_outcomes failed", exc_info=t.exception())
                            if not t.cancelled() and t.exception()
                            else None
                        )
                    )
                    background_tasks.add_task(lambda: None)
                    return {"status": "labeling_outcomes", "pr": pr_number}
                else:
                    logger.info(f"PR closed without merge: {repo_name}#{pr_number} — skipping")
                    return {"status": "ignored", "action": "closed", "reason": "not merged"}
            else:
                # Log ignored actions for visibility
                logger.info(
                    f"Ignoring PR action: {repo_name}#{pr_number} (action: {action}) "
                    f"- only process: opened, synchronize, reopened, ready_for_review"
                )
                return {"status": "ignored", "action": action, "reason": "action not processed"}

        except Exception as e:
            logger.error(f"Error processing webhook: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    # ------------------------------------------------------------------
    # Comment / review events — currently ignored.
    # Full re-reviews on every comment are expensive and don't engage
    # with the specific conversation.  Reviews trigger only on new code
    # (pull_request events above).  A lightweight thread-reply agent
    # may be added later as a separate flow.
    # ------------------------------------------------------------------
    elif event in ("issue_comment", "pull_request_review_comment", "pull_request_review"):
        logger.debug("Ignoring %s event — reviews trigger only on new code", event)
        return {"status": "ignored", "event": event, "reason": "comment events disabled"}

    # Log ignored event types
    logger.info(f"Ignoring event type: {event} - unsupported event")
    return {"status": "ignored", "event": event, "reason": "event type not processed"}


async def _run_fidelity_analysis(
    github_client: GitHubAPIClient,
    repo_full_name: str,
    pr_context,
) -> tuple[str, FidelityResult | None]:
    """
    Run fidelity analysis comparing PR changes to design plan.

    Args:
        github_client: GitHub API client
        repo_full_name: Repository full name (owner/repo)
        pr_context: PR context with branch, title, description, diff

    Returns:
        Tuple of (formatted fidelity report markdown, FidelityResult or None)
    """

    try:
        # Extract ticket ID from PR metadata
        ticket_id = extract_ticket_id(
            branch_name=pr_context.head_branch,
            pr_title=pr_context.title,
            pr_description=pr_context.description,
        )

        if not ticket_id:
            logger.info("Fidelity: No ticket ID found in PR metadata")
            return format_fidelity_report(no_ticket=True), None

        # Fetch plan file from the PR branch (plan is part of the PR)
        plan_path = settings.fidelity_plan_path_pattern.format(ticket_id=ticket_id)
        plan_content = await fetch_plan_content(
            github_client,
            repo_full_name,
            ticket_id,
            ref=pr_context.head_sha,
        )

        if not plan_content:
            logger.info(f"Fidelity: No plan file found for {ticket_id}")
            return (
                format_fidelity_report(
                    no_plan=True,
                    ticket_id=ticket_id,
                    plan_path=plan_path,
                ),
                None,
            )

        # Run fidelity analysis
        logger.info(f"Fidelity: Analyzing {ticket_id} against plan")
        result = await analyze_fidelity(
            plan_content=plan_content,
            pr_title=pr_context.title,
            diff=pr_context.diff,
            ticket_id=ticket_id,
        )

        return format_fidelity_report(result=result, ticket_id=ticket_id), result

    except Exception as e:
        logger.error(f"Fidelity analysis error: {e}", exc_info=True)
        return "", None  # Don't fail the review, just skip fidelity


async def process_pr_review(
    repo_full_name: str,
    pr_number: int,
    installation_id: int,
    trigger_reason: str = "pull_request",
    notify_progress: bool = True,
    synchronize_base_sha: str | None = None,
) -> None:
    """
    Process a PR review in the background.

    Uses a semaphore to limit concurrent reviews and prevent overwhelming the system.

    Args:
        repo_full_name: Repository full name (owner/repo)
        pr_number: Pull request number
        installation_id: GitHub App installation ID
        trigger_reason: Text describing what caused the review
        notify_progress: Whether to post a status comment before reviewing
        synchronize_base_sha: Previous head SHA for synchronize events
    """
    # Acquire semaphore to limit concurrent reviews
    semaphore = get_review_semaphore()
    review_start_time = time.time()
    db_review_id: int | None = None
    progress_comment_id: int | None = None

    try:
        async with semaphore:
            waiting = settings.max_concurrent_reviews - semaphore._value - 1
            logger.info(
                f"Starting review for {repo_full_name}#{pr_number} "
                f"(trigger={trigger_reason}, {waiting} other review(s) in progress)"
            )

            # Create in-progress review row in database
            if settings.database_enabled:
                db_review_id = await ReviewService.start_review(
                    repo_full_name=repo_full_name,
                    pr_number=pr_number,
                    trigger_reason=trigger_reason,
                    started_at=datetime.fromtimestamp(review_start_time, tz=timezone.utc),
                )

            # Initialize GitHub client
            github_client = GitHubAPIClient(installation_id)

            # Post initial comment for main PR events only
            if notify_progress:
                progress_comment_id = await github_client.post_comment(
                    repo_full_name,
                    pr_number,
                    "🐻 Baloo is reviewing your code... This may take a moment.",
                )

            # Fetch PR context
            pr_context = await github_client.get_pr_context(repo_full_name, pr_number)
            changed_files_scope: set[str] | None = None
            changed_line_scope: dict[str, set[int]] = {}
            review_mode = "full_pr"
            review_mode_reason = "Non-synchronize trigger"
            review_context = pr_context
            if trigger_reason == "pull_request:synchronize" and synchronize_base_sha:
                try:
                    (
                        changed_files_scope,
                        changed_line_scope,
                        changed_files_changed,
                        scoped_diff,
                    ) = await github_client.get_changed_scope_between_commits(
                        repo_full_name=repo_full_name,
                        base_sha=synchronize_base_sha,
                        head_sha=pr_context.head_sha,
                    )
                    review_mode, review_mode_reason = await _decide_synchronize_review_mode(
                        pr_context=pr_context,
                        changed_files_changed=changed_files_changed,
                        scoped_diff=scoped_diff,
                    )
                    logger.info(
                        "Synchronize review mode for %s#%s: %s (%s)",
                        repo_full_name,
                        pr_number,
                        review_mode,
                        review_mode_reason,
                    )
                    if review_mode == "scoped" and changed_files_changed and scoped_diff:
                        scoped_metadata = pr_context.metadata.model_copy(
                            update={"files_changed": changed_files_changed}
                        )
                        review_context = pr_context.model_copy(
                            update={"metadata": scoped_metadata, "diff": scoped_diff}
                        )
                        logger.info(
                            "Using scoped review context (%d file(s)) for %s#%s",
                            len(changed_files_changed),
                            repo_full_name,
                            pr_number,
                        )
                except Exception as exc:
                    logger.warning(
                        "Failed to prepare synchronize scope for %s#%s: %s",
                        repo_full_name,
                        pr_number,
                        exc,
                    )
                    review_mode = "full_pr"
                    review_mode_reason = f"Scope preparation failed: {exc}"

            # Run fidelity analysis and main review concurrently
            fidelity_report_text = ""
            fidelity_result = None
            if settings.fidelity_enabled:
                fidelity_report_text, fidelity_result = await _run_fidelity_analysis(
                    github_client, repo_full_name, review_context
                )

            # Initialize agent and perform review
            from baloo.agent.client import BalooAgent

            agent = BalooAgent()
            agent_result = await agent.review_pr(review_context, review_id=db_review_id)
            agent_metadata = agent_result.metadata
            review_result = agent_result

            # FP verification pass (LLM-powered, before heuristic filter)
            if settings.fp_verification_enabled and review_result.comments:
                from baloo.processor.fp_verifier import FPVerifier

                verifier = FPVerifier()
                fp_result = await verifier.verify(review_result.comments, pr_context)
                # Build a fresh metadata dict rather than mutating the agent
                # result's dict via aliasing — keeps provenance explicit and
                # avoids breakage if ReviewResult ever copies its metadata.
                merged_metadata = {
                    **review_result.metadata,
                    "fp_verification": {
                        "total": fp_result.stats.total_verified,
                        "kept": fp_result.stats.kept,
                        "rejected": fp_result.stats.rejected,
                        "errors": fp_result.stats.errors,
                        "cost_usd": fp_result.stats.total_cost_usd,
                        "duration_seconds": fp_result.stats.duration_seconds,
                    },
                }
                review_result = ReviewResult(
                    summary=review_result.summary,
                    comments=fp_result.verified,
                    approve=review_result.approve,
                    request_changes=review_result.request_changes,
                    metadata=merged_metadata,
                )
                # Keep `agent_metadata` in sync so the final ReviewResult
                # built below (which re-uses agent_metadata) still carries
                # the fp_verification stats forward to the DB row.
                agent_metadata = merged_metadata
                logger.info(
                    "FP verification: %d/%d findings kept (rejected %d)",
                    fp_result.stats.kept,
                    fp_result.stats.total_verified,
                    fp_result.stats.rejected,
                )

            findings_filter = FindingsFilter()
            filtered_comments = findings_filter.filter_findings(review_result.comments)
            filtered_comments, skipped_similar_repeats = _dedupe_similar_findings(filtered_comments)

            # Merge inline review threads with synthetic threads built from
            # issue-level comments (the 422-fallback path).  Without this,
            # findings posted as issue comments are invisible to dedup.
            all_threads = list(pr_context.discussion_threads)
            all_threads.extend(_threads_from_issue_comments(pr_context.issue_comments))
            thread_lookup = _build_thread_lookup(all_threads)
            fresh_comments: list[ReviewComment] = []
            follow_up_comments: list[tuple[DiscussionThread, ReviewComment]] = (
                []
            )  # reserved for future conversational thread agent
            skipped_duplicates = 0
            skipped_resolved = 0
            skipped_responded = 0
            skipped_unchanged_scope = 0
            skipped_outside_line_scope = 0

            for comment in filtered_comments:
                thread = _match_thread(thread_lookup, comment)
                if not thread or not thread.is_baloo_thread:
                    if review_mode == "scoped":
                        if (
                            changed_files_scope is not None
                            and comment.path not in changed_files_scope
                        ):
                            skipped_unchanged_scope += 1
                            continue
                        if changed_files_scope is not None and not _within_changed_line_scope(
                            comment, changed_line_scope
                        ):
                            skipped_outside_line_scope += 1
                            continue
                    fresh_comments.append(comment)
                    continue

                # Thread was resolved (GitHub "Resolve conversation").
                # Check before awaiting_response because a developer can
                # resolve a thread without replying, leaving both flags set.
                if thread.resolved:
                    skipped_resolved += 1
                    logger.info(
                        "Skipping resolved finding: %s:%s (thread %s)",
                        comment.path,
                        comment.line,
                        thread.id,
                    )
                    continue

                if thread.awaiting_response:
                    skipped_duplicates += 1
                    continue

                # Developer responded (not resolved, not awaiting) — they've
                # addressed the finding (fixed, declined, or discussed).
                # Don't re-litigate; just note these threads exist.
                skipped_responded += 1
                continue

            decision_comments = fresh_comments + [comment for _, comment in follow_up_comments]

            approve, request_changes = DecisionEngine.make_decision(
                decision_comments, fidelity_result=fidelity_result
            )
            awaiting_threads = pr_context.awaiting_response_threads

            if awaiting_threads and not request_changes and not decision_comments:
                request_changes = True

            decision_summary = DecisionEngine.get_decision_summary(approve, request_changes)

            summary_text = CommentFormatter.format_summary(decision_comments, agent_metadata)
            summary_text = f"{summary_text}\n\n{decision_summary}"

            if skipped_responded:
                summary_text += f"\n\n💬 Skipped {skipped_responded} thread(s) with developer responses (not re-reviewed)."
            if skipped_duplicates:
                summary_text += f"\n\n↪️ Skipped {skipped_duplicates} existing Baloo thread(s) already awaiting a response."
            if skipped_resolved:
                summary_text += f"\n\n✅ Skipped {skipped_resolved} resolved thread(s)."
            if skipped_similar_repeats:
                summary_text += (
                    f"\n\n🧹 Collapsed {skipped_similar_repeats} near-duplicate finding(s) "
                    "from this run."
                )
            if skipped_unchanged_scope:
                summary_text += (
                    f"\n\n🧭 Skipped {skipped_unchanged_scope} finding(s) outside files changed "
                    "in the latest push."
                )
            if skipped_outside_line_scope:
                summary_text += (
                    f"\n\n📏 Skipped {skipped_outside_line_scope} finding(s) not on or near "
                    "lines changed in the latest push."
                )
            if awaiting_threads:
                summary_text += (
                    f"\n\n⏳ {awaiting_threads} Baloo thread(s) remain open from earlier reviews."
                )

            review_result = ReviewResult(
                summary=summary_text,
                comments=fresh_comments,
                approve=approve,
                request_changes=request_changes,
                metadata=agent_metadata,
            )

            severity_counts = count_by_severity(decision_comments)

            logger.info(
                f"Actionable findings: {len(decision_comments)} total "
                f"(Critical: {severity_counts.get(ReviewSeverity.CRITICAL.value, 0)}, "
                f"High: {severity_counts.get(ReviewSeverity.HIGH.value, 0)}, "
                f"Medium: {severity_counts.get(ReviewSeverity.MEDIUM.value, 0)}, "
                f"Low: {severity_counts.get(ReviewSeverity.LOW.value, 0)}), "
                f"follow_ups={len(follow_up_comments)}, skipped_responded={skipped_responded}, "
                f"skipped_duplicates={skipped_duplicates}, skipped_resolved={skipped_resolved}, "
                f"skipped_similar_repeats={skipped_similar_repeats}, "
                f"skipped_unchanged_scope={skipped_unchanged_scope}, "
                f"skipped_outside_line_scope={skipped_outside_line_scope}, "
                f"review_mode={review_mode}, "
                f"approve={approve}, request_changes={request_changes}"
            )

            # Reply within existing threads before posting new review comments
            for thread, comment in follow_up_comments:
                reply_body = (
                    comment.body
                    if "Baloo follow-up" in comment.body
                    else f"🔁 **Baloo follow-up:**\n\n{comment.body}"
                )
                success = await github_client.reply_to_review_comment(
                    repo_full_name,
                    thread.root_comment_id or thread.id,
                    reply_body,
                )
                if success:
                    logger.info(
                        f"Posted follow-up for {repo_full_name}#{pr_number} at {thread.path}:{thread.line}"
                    )
                else:
                    logger.warning(
                        f"Skipped follow-up for outdated comment at {thread.path}:{thread.line} "
                        f"(comment_id={thread.root_comment_id or thread.id})"
                    )

            # Route new findings by severity for posting/logging
            routed = route_findings(review_result.comments)
            posted_review_result: PostedReviewResult | None = None
            logger.info(
                f"New findings routed: {len(routed['review'])} blocking (CRITICAL/HIGH), "
                f"{len(routed['checks'])} non-blocking (MEDIUM)"
            )

            # Post MEDIUM as GitHub Check (non-blocking) if feature enabled
            if routed["checks"] and settings.review_use_checks_api:
                logger.info(f"Posting {len(routed['checks'])} MEDIUM issues as GitHub Check")
                try:
                    from baloo.github.checks_api import GitHubChecksClient

                    checks_client = GitHubChecksClient(installation_id)

                    check_run_id = await checks_client.create_check_run(
                        repo_full_name=repo_full_name,
                        commit_sha=pr_context.head_sha,
                        name="Baloo Code Quality",
                        conclusion="neutral",
                        summary=f"Found {len(routed['checks'])} code quality issue(s) (MEDIUM severity)",
                    )

                    await checks_client.add_annotations(
                        repo_full_name=repo_full_name,
                        check_run_id=check_run_id,
                        findings=routed["checks"],
                    )

                    logger.info(
                        f"Successfully posted GitHub Check with {len(routed['checks'])} annotations"
                    )

                except Exception as check_error:
                    logger.error(f"Failed to post GitHub Check: {check_error}", exc_info=True)
                    # Fallback: Post MEDIUM findings as regular comments
                    logger.warning("Falling back to posting MEDIUM findings as issue comments")
                    for finding in routed["checks"]:
                        comment_body = (
                            f"**[{finding.severity.value}] {finding.category.value}** - {finding.path}:{finding.line}\n\n"
                            f"{finding.body}"
                        )
                        await github_client.post_comment(repo_full_name, pr_number, comment_body)

            has_new_feedback = bool(routed["review"] or follow_up_comments or routed["checks"])

            if request_changes and (routed["review"] or follow_up_comments):
                logger.info("Posting request-changes review with new or follow-up findings")
                posted_result = await github_client.post_review(
                    repo_full_name,
                    pr_number,
                    ReviewResult(
                        summary=review_result.summary,
                        comments=routed["review"],
                        approve=False,
                        request_changes=True,
                    ),
                    diff=pr_context.diff,
                )
                if isinstance(posted_result, PostedReviewResult):
                    posted_review_result = posted_result
                    if posted_result.dropped:
                        logger.warning(
                            "Dropped %d/%d blocking review finding(s) while posting %s#%s",
                            len(posted_result.dropped),
                            posted_result.attempted,
                            repo_full_name,
                            pr_number,
                        )
            elif request_changes and not has_new_feedback:
                logger.info(
                    "Baloo is still waiting on existing threads; no new review posted to avoid noise."
                )

            # Post approval review if no blocking issues
            if not request_changes and approve:
                logger.info("No blocking issues found, posting approval review")
                approval_msg = "✅ No critical or high severity issues found. Safe to merge!"
                if routed["checks"]:
                    approval_msg += f"\n\n💡 {len(routed['checks'])} medium severity suggestion(s) available in the Checks tab."

                await github_client.post_review(
                    repo_full_name,
                    pr_number,
                    ReviewResult(
                        summary=approval_msg,
                        comments=[],  # No inline comments for approval
                        approve=True,
                        request_changes=False,
                    ),
                    diff=pr_context.diff,
                )
            # Update progress comment with completion status
            review_duration = int(time.time() - review_start_time)
            if progress_comment_id:
                if has_new_feedback or (routed["review"] or follow_up_comments):
                    # Review posted findings - update with summary
                    counts = count_by_severity(decision_comments)
                    completion_msg = (
                        f"🐻 Baloo review completed in {review_duration}s.\n\n"
                        f"Found {len(decision_comments)} issue(s): "
                        f"{counts.get(ReviewSeverity.CRITICAL.value, 0)} critical, "
                        f"{counts.get(ReviewSeverity.HIGH.value, 0)} high, "
                        f"{counts.get(ReviewSeverity.MEDIUM.value, 0)} medium, "
                        f"{counts.get(ReviewSeverity.LOW.value, 0)} low."
                    )
                    if posted_review_result is not None:
                        completion_msg += (
                            f"\n\nPosted {posted_review_result.posted} inline comment(s)."
                        )
                        if posted_review_result.dropped:
                            completion_msg += (
                                f" Dropped {len(posted_review_result.dropped)} inline finding(s) "
                                "that could not be placed on the diff; details were logged."
                            )
                elif not request_changes and approve:
                    completion_msg = (
                        f"✅ Baloo review completed in {review_duration}s. No issues found!"
                    )
                elif awaiting_threads:
                    completion_msg = (
                        f"🐻 Baloo review completed in {review_duration}s. "
                        f"Still waiting on {awaiting_threads} existing thread(s)."
                    )
                else:
                    completion_msg = (
                        f"🐻 Baloo review completed in {review_duration}s. No new issues found."
                    )

                try:
                    await github_client.edit_comment(
                        repo_full_name, progress_comment_id, completion_msg
                    )
                except Exception as edit_err:
                    logger.warning(f"Failed to update progress comment: {edit_err}")

            # Post fidelity report as separate comment
            if fidelity_report_text:
                try:
                    if _has_existing_static_fidelity_report(
                        pr_context.issue_comments, fidelity_report_text
                    ):
                        logger.info(
                            "Skipping duplicate static fidelity report for %s#%s",
                            repo_full_name,
                            pr_number,
                        )
                    else:
                        await github_client.post_comment(
                            repo_full_name, pr_number, fidelity_report_text
                        )
                        logger.info(f"Posted fidelity report for {repo_full_name}#{pr_number}")
                except Exception as fidelity_err:
                    logger.warning(f"Failed to post fidelity report: {fidelity_err}")

            logger.info(
                f"Review completed for {repo_full_name}#{pr_number}: "
                f"{len(routed['review'])} blocking, {len(routed['checks'])} non-blocking"
            )

            # Update review row in database with results
            if settings.database_enabled and db_review_id:
                review_metadata = review_result.metadata
                fidelity_metadata = fidelity_result.metadata if fidelity_result else {}

                # Aggregate costs and tokens
                total_input_tokens = (review_metadata.get("input_tokens") or 0) + (
                    fidelity_metadata.get("input_tokens") or 0
                )
                total_output_tokens = (review_metadata.get("output_tokens") or 0) + (
                    fidelity_metadata.get("output_tokens") or 0
                )
                total_cost_usd = _total_review_cost_usd(review_metadata, fidelity_metadata)

                # Detect agent soft-failures: agent caught an error
                # internally and returned 0 findings
                agent_had_error = review_metadata.get("agent_error", False)
                error_category = review_metadata.get("error_category")
                error_detail = review_metadata.get("error_detail")
                fallback_model = (
                    review_metadata.get("primary_model")
                    if review_metadata.get("fallback_used")
                    else None
                )

                if agent_had_error:
                    review_status = "agent_error"
                elif approve:
                    review_status = "approved"
                elif request_changes:
                    review_status = "changes_requested"
                else:
                    review_status = "commented"

                complete_data = ReviewCompleteDTO(
                    pr_title=pr_context.title,
                    pr_author=pr_context.author,
                    commit_sha=pr_context.head_sha,
                    review_status=review_status,
                    completed_at=datetime.now(timezone.utc),
                    duration_seconds=review_duration,
                    model_used=review_metadata.get("model"),
                    tokens_input=total_input_tokens,
                    tokens_output=total_output_tokens,
                    cost_usd=total_cost_usd,
                    agent_turns=review_metadata.get("num_turns"),
                    files_examined=len(pr_context.files_changed),
                    auto_approved=approve and not request_changes,
                    fidelity_score=(fidelity_result.fidelity_score if fidelity_result else None),
                    error_message=error_detail,
                    error_category=error_category,
                    fallback_model=fallback_model,
                    findings=[
                        {
                            "file_path": c.path,
                            "line_number": c.line,
                            "severity": c.severity,
                            "category": c.category,
                            "body": c.body,
                        }
                        for c in decision_comments
                    ],
                )

                await ReviewService.complete_review(
                    review_id=db_review_id,
                    data=complete_data,
                )

    except asyncio.CancelledError:
        logger.info(f"Review for {repo_full_name}#{pr_number} was cancelled")
        if settings.database_enabled and db_review_id:
            try:
                # Update DB with cancelled status
                complete_data = ReviewCompleteDTO(
                    review_status="cancelled",
                    completed_at=datetime.now(timezone.utc),
                    duration_seconds=time.time() - review_start_time,
                    error_message="Review cancelled due to new commit",
                )
                await ReviewService.complete_review(
                    review_id=db_review_id,
                    data=complete_data,
                )
            except Exception as db_err:
                logger.warning(f"Failed to mark review as cancelled in DB: {db_err}")

        # Update progress comment if possible
        if progress_comment_id:
            try:
                github_client = GitHubAPIClient(installation_id)
                await github_client.edit_comment(
                    repo_full_name,
                    progress_comment_id,
                    "👋 This review was cancelled because a new commit was pushed. Baloo is starting a new review!",
                )
            except Exception:
                pass
        raise  # Re-raise so asyncio knows it was cancelled

    except Exception as e:
        logger.error(f"Critical error in process_pr_review: {e}", exc_info=True)
        # Update review row with error status
        if settings.database_enabled and db_review_id:
            try:
                complete_data = ReviewCompleteDTO(
                    review_status="error",
                    completed_at=datetime.now(timezone.utc),
                    duration_seconds=time.time() - review_start_time,
                    error_message=str(e),
                )
                await ReviewService.complete_review(review_id=db_review_id, data=complete_data)
            except Exception:
                pass

        # Try to update progress comment with error
        if progress_comment_id:
            try:
                github_client = GitHubAPIClient(installation_id)
                user_msg = f"🐻 Baloo encountered an error during review: {str(e)}"
                await github_client.edit_comment(repo_full_name, progress_comment_id, user_msg)
            except Exception:
                pass
    finally:
        # Clean up the task registry
        key = (repo_full_name, pr_number)
        if active_reviews.get(key) == asyncio.current_task():
            del active_reviews[key]
