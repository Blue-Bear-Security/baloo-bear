"""FastAPI webhook handler for GitHub events."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from baloo.config.settings import settings
from baloo.db.engine import close_db, init_db
from baloo.github.api_client import GitHubAPIClient
from baloo.github.auth import verify_repo_belongs_to_installation, verify_webhook_signature
from baloo.github.models import PullRequestWebhookPayload
from baloo.outcomes.labeler import label_pr_outcomes
from baloo.review.orchestrator import (
    _process_thread_reply,
    active_reviews,
    cancel_existing_review,
    process_pr_review,
)

logger = logging.getLogger(__name__)

_recent_delivery_ids: dict[str, float] = {}


def _mark_delivery_seen(delivery_id: str | None, ttl_seconds: int) -> bool:
    """Return True when this GitHub delivery ID was already seen within ttl_seconds."""
    if not delivery_id:
        return False
    now = time.monotonic()
    expired = [k for k, seen_at in _recent_delivery_ids.items() if now - seen_at > ttl_seconds]
    for k in expired:
        _recent_delivery_ids.pop(k, None)
    if delivery_id in _recent_delivery_ids:
        return True
    _recent_delivery_ids[delivery_id] = now
    return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize and tear down database."""
    if settings.database_enabled and settings.database_url:
        logger.info("Database enabled, initializing...")
        await init_db(settings.database_url)
    elif settings.database_enabled:
        logger.warning(
            "DATABASE_ENABLED=true but DATABASE_URL is not set — "
            "database features will be unavailable. "
            "Set DATABASE_URL to a valid PostgreSQL connection string."
        )
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


@app.get("/")
async def root() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "baloo"}


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint for load balancer probes."""
    return {"status": "ok"}


async def _validate_webhook_security(
    installation_id: int | None,
    repo_full_name: str | None,
) -> dict | None:
    """
    Validate installation identity and repo ownership for an incoming webhook.

    Returns a skip-response dict if the webhook should be silently skipped,
    None if all checks pass. Raises HTTPException on security violations.
    """
    import httpx

    from baloo.config.settings import get_settings
    from baloo.github.auth import GitHubAuth

    if installation_id is None:
        raise HTTPException(status_code=400, detail="Missing installation_id")

    current_settings = get_settings()

    # If this broker is scoped to a specific installation, drop anything else silently
    if (
        current_settings.installation_id
        and str(installation_id) != current_settings.installation_id
    ):
        logger.debug(
            "Webhook skipped — installation %s not configured for this broker",
            installation_id,
        )
        return {"status": "skipped", "reason": "installation not configured for this broker"}

    # Confirm this installation has active auth
    try:
        GitHubAuth().get_installation_token(installation_id)
    except httpx.HTTPStatusError as exc:
        logger.warning("Token fetch failed for installation %s: %s", installation_id, exc)
        raise HTTPException(status_code=403, detail="Invalid installation")

    # Confirm the repository belongs to this installation
    if repo_full_name and not await verify_repo_belongs_to_installation(
        installation_id, repo_full_name
    ):
        logger.warning(
            "Repo %s not accessible for installation %s — possible cross-tenant payload",
            repo_full_name,
            installation_id,
        )
        raise HTTPException(
            status_code=403,
            detail="Repository not accessible for this installation",
        )

    return None


@app.post("/webhook")
async def handle_webhook(
    request: Request, background_tasks: BackgroundTasks
) -> dict[str, str | int]:
    """Handle GitHub webhook events."""
    # Verify webhook signature
    signature = request.headers.get("X-Hub-Signature-256")
    body = await request.body()

    if not verify_webhook_signature(body, signature):
        logger.warning("Invalid webhook signature")
        raise HTTPException(status_code=403, detail="Invalid signature")

    # Parse event type and payload
    event = request.headers.get("X-GitHub-Event")
    delivery_id = request.headers.get("X-GitHub-Delivery")

    # Lifecycle events have no repository payload — return early before dedup and security validation
    if event in ("ping", "installation", "installation_repositories", "meta"):
        logger.info("Ignoring GitHub App lifecycle event: %s", event)
        return {"status": "ignored", "event": event or "", "reason": "app lifecycle event"}

    if _mark_delivery_seen(delivery_id, settings.webhook_delivery_dedupe_ttl_seconds):
        logger.info("Ignoring duplicate webhook delivery %s", delivery_id)
        return {"status": "skipped", "reason": "duplicate delivery"}

    payload = await request.json()

    # Security validation: confirm installation identity and repo ownership
    _installation_id = payload.get("installation", {}).get("id")
    _repo_full_name = payload.get("repository", {}).get("full_name")
    _skip = await _validate_webhook_security(_installation_id, _repo_full_name)
    if _skip is not None:
        return _skip

    logger.info(
        "Received %s event delivery=%s repo=%s installation=%s",
        event,
        delivery_id or "",
        _repo_full_name or "",
        _installation_id or "",
    )

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
                    async with GitHubAPIClient(webhook_payload.installation.id) as _gc:
                        is_merge, merge_reason = await _gc.is_merge_or_sync_commit(
                            repo_name, head_sha, base_branch
                        )
                    if is_merge:
                        logger.info(f"Skipping review for {repo_name}#{pr_number}: {merge_reason}")
                        return {"status": "skipped", "reason": merge_reason}

                # Cancel redundant review if one exists
                cancel_existing_review(repo_name, pr_number)

                # Check current queue status (after cancel so the old task isn't counted)
                active_count = sum(1 for t in active_reviews.values() if not t.done())
                logger.info(
                    f"Queuing review: {repo_name}#{pr_number} (action: {action}) "
                    f"- {active_count} review(s) active (running or queued)"
                )

                # Process PR review in background
                task = asyncio.create_task(
                    process_pr_review(
                        webhook_payload.repository.full_name,
                        pr_number,
                        webhook_payload.installation.id,
                        f"pull_request:{action}",
                        True,
                        before_sha if action == "synchronize" else None,
                        head_sha or "",
                        delivery_id,
                    )
                )
                active_reviews[(repo_name, pr_number)] = task

                # Add to FastAPI background tasks so it isn't garbage collected early
                background_tasks.add_task(lambda: None)

                return {"status": "queued", "active_count": active_count}
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
                logger.info(
                    f"Ignoring PR action: {repo_name}#{pr_number} (action: {action}) "
                    f"- only process: opened, synchronize, reopened, ready_for_review"
                )
                return {"status": "ignored", "action": action, "reason": "action not processed"}

        except Exception as e:
            logger.error(f"Error processing webhook: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    elif event == "pull_request_review_comment":
        action = payload.get("action")

        # Only handle new comments (not edits or deletions)
        if action != "created":
            return {"status": "ignored", "event": event, "reason": f"action={action}"}

        if not settings.thread_agent_enabled:
            return {"status": "ignored", "event": event, "reason": "thread agent disabled"}

        comment_data = payload.get("comment", {})
        in_reply_to_id = comment_data.get("in_reply_to_id")
        comment_author = (comment_data.get("user") or {}).get("login", "")
        comment_body = comment_data.get("body", "")

        # Must be a reply to an existing comment
        if not in_reply_to_id:
            return {"status": "ignored", "event": event, "reason": "not a reply"}

        # Ignore Baloo's own comments
        from baloo.github.discussions import is_baloo_actor

        if is_baloo_actor(comment_author, comment_body):
            return {"status": "ignored", "event": event, "reason": "self-reply"}

        pr_data = payload.get("pull_request", {})
        repo_data = payload.get("repository", {})
        installation_id = payload.get("installation", {}).get("id")

        repo_full_name = repo_data.get("full_name", "")
        pr_number = pr_data.get("number", 0)

        logger.info(
            "Thread reply on %s#%s by @%s (reply_to=%s)",
            repo_full_name,
            pr_number,
            comment_author,
            in_reply_to_id,
        )

        # Process thread reply in background
        background_tasks.add_task(
            _process_thread_reply,
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            installation_id=installation_id,
            comment_data=comment_data,
            in_reply_to_id=in_reply_to_id,
            head_sha=pr_data.get("head", {}).get("sha", ""),
        )

        return {"status": "queued", "event": event, "action": "thread_reply"}

    elif event in ("issue_comment", "pull_request_review"):
        logger.debug("Ignoring %s event — reviews trigger only on new code", event)
        return {"status": "ignored", "event": event, "reason": "comment events disabled"}

    # Log ignored event types
    logger.info(f"Ignoring event type: {event} - unsupported event")
    return {"status": "ignored", "event": event, "reason": "event type not processed"}
