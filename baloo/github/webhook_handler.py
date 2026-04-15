"""FastAPI webhook handler for GitHub events."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from baloo.config.settings import settings
from baloo.db.engine import close_db, init_db
from baloo.db.service import ReviewCompleteDTO, ReviewService
from baloo.fidelity.fidelity_analyzer import analyze_fidelity
from baloo.fidelity.fidelity_report import format_fidelity_report
from baloo.fidelity.plan_fetcher import fetch_plan_content
from baloo.fidelity.ticket_extractor import extract_ticket_id
from baloo.github.api_client import GitHubAPIClient
from baloo.github.auth import verify_webhook_signature
from baloo.github.models import (
    DiscussionThread,
    PullRequestWebhookPayload,
    ReviewComment,
    ReviewResult,
)
from baloo.processor.decision_engine import DecisionEngine
from baloo.processor.findings_filter import FindingsFilter
from baloo.processor.severity_router import (
    ReviewSeverity,
    count_by_severity,
    route_findings,
)

logger = logging.getLogger(__name__)


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


def get_review_semaphore() -> asyncio.Semaphore:
    """Get or create the review semaphore with the configured limit."""
    global review_semaphore
    if review_semaphore is None:
        review_semaphore = asyncio.Semaphore(settings.max_concurrent_reviews)
        logger.info(f"Initialized review queue with max {settings.max_concurrent_reviews} concurrent reviews")
    return review_semaphore


@app.get("/")
async def root() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "baloo"}


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


def _is_bot_sender(sender: dict | None) -> bool:
    """Return True if the webhook sender is a bot (to avoid feedback loops)."""
    if not sender:
        return False
    if sender.get("type") == "Bot":
        return True
    login = (sender.get("login") or "").lower()
    return login.endswith("[bot]") or "baloo" in login


# Number of lines to search above/below when matching threads (handles line drift)
LINE_MATCH_TOLERANCE = 5


def _build_thread_lookup(
    threads: list[DiscussionThread],
) -> dict[str, list[DiscussionThread]]:
    """
    Create a lookup for Baloo threads grouped by file path.

    Returns a dict mapping file path -> list of threads in that file,
    sorted by line number for efficient range searching.
    """
    lookup: dict[str, list[DiscussionThread]] = {}
    for thread in threads:
        if not thread.path or thread.line is None:
            continue
        if thread.path not in lookup:
            lookup[thread.path] = []
        lookup[thread.path].append(thread)

    # Sort threads by line number within each file
    for path in lookup:
        lookup[path].sort(key=lambda t: t.line or 0)

    return lookup


def _extract_issue_signature(body: str) -> str:
    """
    Extract a normalized signature from a Baloo comment for similarity matching.

    This extracts the category and key terms from the issue description
    to identify semantically similar issues even if line numbers drift.
    """
    # Normalize whitespace and lowercase
    normalized = " ".join(body.lower().split())

    # Try to extract category from Baloo's format: **[SEVERITY] Category** - description
    import re
    match = re.search(r"\*\*\[(?:critical|high|medium|low)\]\s*(\w+)\*\*\s*-\s*(.+)", normalized)
    if match:
        category = match.group(1)
        description = match.group(2)

        # Extract key technical terms (identifiers, function names, etc.)
        # This helps match issues about the same code construct
        key_terms = set()

        # Find identifiers (camelCase, snake_case, etc.)
        identifiers = re.findall(r'\b[a-z_][a-z0-9_]*(?:[A-Z][a-z0-9]*)*\b', description)
        key_terms.update(identifiers)

        # Find quoted terms
        quoted = re.findall(r'[`\'"]([^`\'"]+)[`\'"]', description)
        for q in quoted:
            key_terms.update(q.lower().split())

        # Include first 100 chars of description plus key terms
        return f"{category}:{description[:100]} {' '.join(sorted(key_terms))}"

    # Fallback: use first 150 chars
    return normalized[:150]


def _match_thread(
    lookup: dict[str, list[DiscussionThread]],
    comment: ReviewComment,
) -> DiscussionThread | None:
    """
    Find an existing discussion thread matching a review comment.

    Uses fuzzy matching:
    1. First checks for exact (path, line) match
    2. Then checks within ±LINE_MATCH_TOLERANCE lines for similar issues

    Scoring:
    - line_score: (LINE_MATCH_TOLERANCE - distance), max 5 for exact match
    - content_score: Jaccard similarity (0-1) * 15
    - Same category bonus: +3 if categories match
    - Minimum threshold: 4 (to catch line drift with similar issues)
    """
    if not comment.path or comment.line is None:
        return None

    threads_in_file = lookup.get(comment.path)
    if not threads_in_file:
        return None

    comment_signature = _extract_issue_signature(comment.body)
    comment_category = comment_signature.split(":")[0] if ":" in comment_signature else ""

    best_match: DiscussionThread | None = None
    best_score = 0.0

    for thread in threads_in_file:
        if thread.line is None:
            continue

        line_distance = abs(thread.line - comment.line)

        # Skip if outside tolerance range
        if line_distance > LINE_MATCH_TOLERANCE:
            continue

        # Check if this is a Baloo thread with similar content
        if thread.is_baloo_thread and thread.comments:
            thread_signature = _extract_issue_signature(thread.comments[0].body)
            thread_category = thread_signature.split(":")[0] if ":" in thread_signature else ""

            # Calculate similarity score (higher is better)
            # Exact line match gets bonus points
            line_score = LINE_MATCH_TOLERANCE - line_distance  # 0-5
            content_score = _calculate_similarity(comment_signature, thread_signature) * 15  # 0-15

            # Bonus for same category (e.g., both "bugs", both "security")
            category_bonus = 3 if comment_category == thread_category else 0

            total_score = line_score + content_score + category_bonus

            if total_score > best_score:
                best_score = total_score
                best_match = thread

    # Threshold of 4 allows:
    # - Exact line match (5) with minimal content similarity
    # - Same category (3) + nearby line (2) + some content overlap
    # - High content similarity (>0.25 * 15 = 3.75) + same category (3) with line drift
    if best_match and best_score >= 4:
        return best_match

    return None


def _calculate_similarity(sig1: str, sig2: str) -> float:
    """
    Calculate similarity between two issue signatures.

    Returns a score between 0 and 1.
    """
    if not sig1 or not sig2:
        return 0.0

    # Simple word overlap similarity
    words1 = set(sig1.split())
    words2 = set(sig2.split())

    if not words1 or not words2:
        return 0.0

    intersection = words1 & words2
    union = words1 | words2

    return len(intersection) / len(union) if union else 0.0


@app.post("/webhook")
async def handle_webhook(request: Request, background_tasks: BackgroundTasks) -> dict[str, str | int]:
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
                    logger.info(
                        f"Skipping draft PR: {repo_name}#{pr_number} (action: {action})"
                    )
                    return {"status": "skipped", "reason": "draft PR"}

                # For synchronize events, check if this is just a merge/sync commit
                head_sha = webhook_payload.pull_request.head.get("sha")
                base_branch = webhook_payload.pull_request.base.get("ref", "main")

                if action == "synchronize" and head_sha:
                    github_client = GitHubAPIClient(webhook_payload.installation.id)
                    is_merge, merge_reason = await github_client.is_merge_or_sync_commit(
                        repo_name, head_sha, base_branch
                    )
                    if is_merge:
                        logger.info(
                            f"Skipping review for {repo_name}#{pr_number}: {merge_reason}"
                        )
                        return {"status": "skipped", "reason": merge_reason}

                # Check current queue status
                semaphore = get_review_semaphore()
                waiting = settings.max_concurrent_reviews - semaphore._value
                logger.info(
                    f"Queuing review: {repo_name}#{pr_number} (action: {action}) "
                    f"- {waiting} review(s) currently running"
                )

                # Process PR review in background
                background_tasks.add_task(
                    process_pr_review,
                    webhook_payload.repository.full_name,
                    pr_number,
                    webhook_payload.installation.id,
                    f"pull_request:{action}",
                    True,
                )

                return {"status": "queued", "queue_depth": waiting}
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
            return format_fidelity_report(
                no_plan=True,
                ticket_id=ticket_id,
                plan_path=plan_path,
            ), None

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
    """
    # Acquire semaphore to limit concurrent reviews
    semaphore = get_review_semaphore()
    async with semaphore:
        waiting = settings.max_concurrent_reviews - semaphore._value - 1
        logger.info(
            f"Starting review for {repo_full_name}#{pr_number} "
            f"(trigger={trigger_reason}, {waiting} other review(s) in progress)"
        )

        progress_comment_id: int | None = None
        review_start_time = time.time()
        db_review_id: int | None = None

        # Create in-progress review row in database
        if settings.database_enabled:
            db_review_id = await ReviewService.start_review(
                repo_full_name=repo_full_name,
                pr_number=pr_number,
                trigger_reason=trigger_reason,
                started_at=datetime.fromtimestamp(
                    review_start_time, tz=timezone.utc
                ),
            )

        try:
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

            # Run fidelity analysis and main review concurrently
            fidelity_report_text = ""
            fidelity_result = None
            if settings.fidelity_enabled:
                fidelity_report_text, fidelity_result = await _run_fidelity_analysis(
                    github_client, repo_full_name, pr_context
                )

            # Initialize agent and perform review
            from baloo.agent.client import BalooAgent
            agent = BalooAgent()
            agent_result = await agent.review_pr(pr_context)
            agent_metadata = agent_result.metadata
            review_result = agent_result

            # FP verification pass (LLM-powered, before heuristic filter)
            if settings.fp_verification_enabled and review_result.comments:
                from baloo.processor.fp_verifier import FPVerifier

                verifier = FPVerifier()
                fp_result = await verifier.verify(review_result.comments, pr_context)
                review_result = ReviewResult(
                    summary=review_result.summary,
                    comments=fp_result.verified,
                    approve=review_result.approve,
                    request_changes=review_result.request_changes,
                    metadata=review_result.metadata,
                )
                review_result.metadata["fp_verification"] = {
                    "total": fp_result.stats.total_verified,
                    "kept": fp_result.stats.kept,
                    "rejected": fp_result.stats.rejected,
                    "errors": fp_result.stats.errors,
                    "cost_usd": fp_result.stats.total_cost_usd,
                    "duration_seconds": fp_result.stats.duration_seconds,
                }
                logger.info(
                    "FP verification: %d/%d findings kept (rejected %d)",
                    fp_result.stats.kept,
                    fp_result.stats.total_verified,
                    fp_result.stats.rejected,
                )

            findings_filter = FindingsFilter()
            filtered_comments = findings_filter.filter_findings(review_result.comments)

            thread_lookup = _build_thread_lookup(pr_context.discussion_threads)
            fresh_comments: list[ReviewComment] = []
            follow_up_comments: list[tuple[DiscussionThread, ReviewComment]] = []
            skipped_duplicates = 0

            for comment in filtered_comments:
                thread = _match_thread(thread_lookup, comment)
                if not thread or not thread.is_baloo_thread:
                    fresh_comments.append(comment)
                    continue

                if thread.awaiting_response:
                    skipped_duplicates += 1
                    continue

                follow_up_comments.append((thread, comment))

            decision_comments = fresh_comments + [comment for _, comment in follow_up_comments]

            approve, request_changes = DecisionEngine.make_decision(
                decision_comments, fidelity_result=fidelity_result
            )
            awaiting_threads = pr_context.awaiting_response_threads

            if awaiting_threads and not request_changes and not decision_comments:
                request_changes = True

            decision_summary = DecisionEngine.get_decision_summary(approve, request_changes)

            summary_text = agent_result.summary
            summary_text = f"{summary_text}\n\n{decision_summary}"

            if follow_up_comments:
                summary_text += (
                    f"\n\n↪️ Baloo added follow-ups to {len(follow_up_comments)} existing thread(s)."
                )
            if skipped_duplicates:
                summary_text += (
                    f"\n\n↪️ Skipped {skipped_duplicates} existing Baloo thread(s) already awaiting a response."
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
                f"follow_ups={len(follow_up_comments)}, skipped_duplicates={skipped_duplicates}, "
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
                        summary=f"Found {len(routed['checks'])} code quality issue(s) (MEDIUM severity)"
                    )

                    await checks_client.add_annotations(
                        repo_full_name=repo_full_name,
                        check_run_id=check_run_id,
                        findings=routed["checks"]
                    )

                    logger.info(f"Successfully posted GitHub Check with {len(routed['checks'])} annotations")

                except Exception as check_error:
                    logger.error(f"Failed to post GitHub Check: {check_error}", exc_info=True)
                    # Fallback: Post MEDIUM findings as regular comments
                    logger.warning("Falling back to posting MEDIUM findings as issue comments")
                    for finding in routed["checks"]:
                        comment_body = (
                            f"**[{finding.severity}] {finding.category}** - {finding.path}:{finding.line}\n\n"
                            f"{finding.body}"
                        )
                        await github_client.post_comment(repo_full_name, pr_number, comment_body)

            has_new_feedback = bool(routed["review"] or follow_up_comments or routed["checks"])

            if request_changes and (routed["review"] or follow_up_comments):
                logger.info("Posting request-changes review with new or follow-up findings")
                await github_client.post_review(
                    repo_full_name,
                    pr_number,
                    ReviewResult(
                        summary=review_result.summary,
                        comments=routed["review"],
                        approve=False,
                        request_changes=True,
                    ),
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
                    approval_msg += (
                        f"\n\n💡 {len(routed['checks'])} medium severity suggestion(s) available in the Checks tab."
                    )

                await github_client.post_review(
                    repo_full_name,
                    pr_number,
                    ReviewResult(
                        summary=approval_msg,
                        comments=[],  # No inline comments for approval
                        approve=True,
                        request_changes=False,
                    ),
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
                elif not request_changes and approve:
                    completion_msg = f"✅ Baloo review completed in {review_duration}s. No issues found!"
                elif awaiting_threads:
                    completion_msg = (
                        f"🐻 Baloo review completed in {review_duration}s. "
                        f"Still waiting on {awaiting_threads} existing thread(s)."
                    )
                else:
                    completion_msg = f"🐻 Baloo review completed in {review_duration}s. No new issues found."

                try:
                    await github_client.edit_comment(repo_full_name, progress_comment_id, completion_msg)
                except Exception as edit_err:
                    logger.warning(f"Failed to update progress comment: {edit_err}")

            # Post fidelity report as separate comment
            if fidelity_report_text:
                try:
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
                total_cost_usd = (review_metadata.get("cost_usd") or 0.0) + (
                    fidelity_metadata.get("cost_usd") or 0.0
                )

                # Detect agent soft-failures: agent caught an error
                # internally and returned 0 findings
                agent_had_error = review_metadata.get("agent_error", False)
                error_category = review_metadata.get("error_category")
                error_detail = review_metadata.get("error_detail")
                fallback_model = review_metadata.get("primary_model") if review_metadata.get("fallback_used") else None

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
                    fidelity_score=(
                        fidelity_result.fidelity_score
                        if fidelity_result
                        else None
                    ),
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

        except Exception as e:
            logger.error(f"Error during PR review: {e}", exc_info=True)

            # Update review row with error status and partial cost if available
            if settings.database_enabled and db_review_id:
                # Extract partial metadata from review_result or the exception
                review_metadata = {}
                if "review_result" in locals():
                    review_metadata = getattr(locals()["review_result"], "metadata", {})
                elif hasattr(e, "metadata"):
                    review_metadata = getattr(e, "metadata", {})

                # Extract fidelity metadata if available
                fidelity_metadata = {}
                if "fidelity_result" in locals() and locals()["fidelity_result"]:
                    fidelity_metadata = getattr(locals()["fidelity_result"], "metadata", {})

                # Total cost and tokens (even for failed reviews)
                total_input_tokens = (review_metadata.get("input_tokens") or 0) + (
                    fidelity_metadata.get("input_tokens") or 0
                )
                total_output_tokens = (review_metadata.get("output_tokens") or 0) + (
                    fidelity_metadata.get("output_tokens") or 0
                )
                total_cost_usd = (review_metadata.get("cost_usd") or 0.0) + (
                    fidelity_metadata.get("cost_usd") or 0.0
                )

                # Classify the exception error
                from baloo.agent.client import BalooAgent
                exc_category = BalooAgent._classify_error(str(e))

                complete_data = ReviewCompleteDTO(
                    review_status="error",
                    completed_at=datetime.now(timezone.utc),
                    duration_seconds=time.time() - review_start_time,
                    tokens_input=total_input_tokens,
                    tokens_output=total_output_tokens,
                    cost_usd=total_cost_usd,
                    error_message=str(e),
                    error_category=exc_category,
                )

                await ReviewService.complete_review(
                    review_id=db_review_id,
                    data=complete_data,
                )

            # Try to update progress comment with error
            review_duration = int(time.time() - review_start_time)
            error_msg = str(e)

            # Check for "Prompt is too long" error and provide helpful message
            if "Prompt is too long" in error_msg or "prompt is too long" in error_msg.lower():
                user_msg = (
                    f"🐻 Baloo couldn't review this PR - the diff is too large ({review_duration}s).\n\n"
                    "**Tip:** Consider breaking this PR into smaller changes, or Baloo will review "
                    "on subsequent commits when the diff is smaller."
                )
            else:
                user_msg = f"🐻 Baloo encountered an error during review ({review_duration}s): {error_msg}"

            try:
                github_client = GitHubAPIClient(installation_id)
                if progress_comment_id:
                    await github_client.edit_comment(repo_full_name, progress_comment_id, user_msg)
                else:
                    await github_client.post_comment(repo_full_name, pr_number, user_msg)
            except Exception:
                logger.error("Failed to post/update error comment", exc_info=True)
