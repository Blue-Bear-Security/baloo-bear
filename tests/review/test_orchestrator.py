"""Tests for review/orchestrator.py — uncovered paths."""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from baloo.github.api_client import PostedReviewResult
from baloo.github.models import (
    DiscussionComment,
    DiscussionThread,
    FindingCategory,
    PRContext,
    ReviewComment,
    ReviewResult,
    ReviewSeverity,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _now():
    return datetime.now(timezone.utc)


def _make_pr_context(
    *,
    repo: str = "org/repo",
    pr_number: int = 1,
    head_sha: str = "abc123",
    diff: str = "+ code",
    threads: list | None = None,
    issue_comments: list | None = None,
) -> MagicMock:
    ctx = MagicMock(spec=PRContext)
    ctx.repo_full_name = repo
    ctx.pr_number = pr_number
    ctx.head_sha = head_sha
    ctx.head_branch = "feat/test"
    ctx.title = "Test PR"
    ctx.description = ""
    ctx.diff = diff
    ctx.discussion_threads = threads or []
    ctx.issue_comments = issue_comments or []
    ctx.awaiting_response_threads = 0
    ctx.files_changed = []
    ctx.author = "dev"
    meta = MagicMock()
    meta.model_copy = MagicMock(return_value=meta)
    ctx.metadata = meta
    ctx.model_copy = MagicMock(return_value=ctx)
    return ctx


def _make_github_client(pr_context=None):
    gc = MagicMock()
    gc.aclose = AsyncMock()
    gc.__aenter__ = AsyncMock(return_value=gc)
    gc.__aexit__ = AsyncMock(return_value=False)
    gc.post_comment = AsyncMock(return_value=42)
    gc.edit_comment = AsyncMock()
    gc.post_review = AsyncMock(return_value=PostedReviewResult(attempted=0, posted=0, dropped=[]))
    gc.reply_to_review_comment = AsyncMock(return_value=True)
    gc.resolve_review_thread = AsyncMock()
    gc.is_merge_or_sync_commit = AsyncMock(return_value=(False, ""))
    gc.get_pr_context = AsyncMock(return_value=pr_context or _make_pr_context())
    return gc


def _make_agent(comments=None, approve=True, request_changes=False, metadata=None):
    agent = MagicMock()
    agent.review_pr = AsyncMock(
        return_value=ReviewResult(
            summary="## Summary",
            comments=comments or [],
            approve=approve,
            request_changes=request_changes,
            metadata=metadata or {},
        )
    )
    return agent


def _base_patches(gc, agent):
    return [
        patch("baloo.review.orchestrator.GitHubAPIClient", return_value=gc),
        patch("baloo.agent.client.BalooAgent", return_value=agent),
        patch("baloo.review.orchestrator.settings.fidelity_enabled", False),
        patch("baloo.review.orchestrator.settings.fp_verification_enabled", False),
        patch("baloo.config.settings.settings.fp_verification_enabled", False),
        patch("baloo.config.settings.settings.review_min_severity", "MEDIUM"),
        patch("baloo.review.orchestrator.settings.database_enabled", False),
        patch("baloo.config.settings.settings.database_enabled", False),
        patch("baloo.review.orchestrator.settings.feedback_signals_enabled", False),
        patch("baloo.review.orchestrator.settings.review_use_checks_api", False),
    ]


async def _run_review(gc, agent, **kwargs):
    from baloo.review.orchestrator import process_pr_review

    defaults: dict[str, Any] = dict(
        repo_full_name="org/repo",
        pr_number=1,
        installation_id=1,
        trigger_reason="pull_request:opened",
        notify_progress=False,
        head_sha="abc123",
    )
    defaults.update(kwargs)
    with ExitStack() as stack:
        for p in _base_patches(gc, agent):
            stack.enter_context(p)
        await process_pr_review(**defaults)


# ---------------------------------------------------------------------------
# Semaphore initialisation
# ---------------------------------------------------------------------------


class TestGetThreadAgentSemaphore:
    def test_first_call_creates_semaphore(self, monkeypatch):
        import baloo.review.orchestrator as orch

        monkeypatch.setattr(orch, "thread_agent_semaphore", None)
        monkeypatch.setenv("THREAD_AGENT_MAX_CONCURRENT", "3")

        sem = orch.get_thread_agent_semaphore()

        assert sem is not None
        assert isinstance(sem, asyncio.Semaphore)


# ---------------------------------------------------------------------------
# Cancellation monitor
# ---------------------------------------------------------------------------


class TestMonitorReviewCancellation:
    @pytest.mark.asyncio
    async def test_cancels_main_task_when_review_cancelled(self):
        from baloo.review.orchestrator import _monitor_review_cancellation

        main_task = asyncio.create_task(asyncio.sleep(10))

        with (
            patch("baloo.review.orchestrator._REVIEW_CANCEL_POLL_SECONDS", 0),
            patch(
                "baloo.review.orchestrator.ReviewService.is_review_cancelled",
                new=AsyncMock(return_value=True),
            ),
        ):
            await _monitor_review_cancellation(
                review_id=1,
                main_task=main_task,
                repo_full_name="org/repo",
                pr_number=1,
            )

        # Give the event loop a chance to actually cancel the task
        try:
            await asyncio.wait_for(asyncio.shield(main_task), timeout=0.1)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        assert main_task.cancelled() or main_task.cancelling() > 0
        if not main_task.done():
            main_task.cancel()

    @pytest.mark.asyncio
    async def test_logs_warning_on_poll_exception_and_continues(self):
        from baloo.review.orchestrator import _monitor_review_cancellation

        call_count = 0

        async def _poll(review_id):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("db unavailable")
            return True

        main_task = asyncio.create_task(asyncio.sleep(10))

        with (
            patch("baloo.review.orchestrator._REVIEW_CANCEL_POLL_SECONDS", 0),
            patch(
                "baloo.review.orchestrator.ReviewService.is_review_cancelled",
                new=AsyncMock(side_effect=_poll),
            ),
        ):
            await _monitor_review_cancellation(
                review_id=1,
                main_task=main_task,
                repo_full_name="org/repo",
                pr_number=1,
            )

        assert call_count == 2
        main_task.cancel()

    @pytest.mark.asyncio
    async def test_exits_when_main_task_finishes(self):
        from baloo.review.orchestrator import _monitor_review_cancellation

        async def _instant():
            return None

        main_task = asyncio.create_task(_instant())
        await main_task

        with patch(
            "baloo.review.orchestrator.ReviewService.is_review_cancelled",
            new=AsyncMock(return_value=False),
        ) as mock_poll:
            await _monitor_review_cancellation(
                review_id=1,
                main_task=main_task,
                repo_full_name="org/repo",
                pr_number=1,
            )

        mock_poll.assert_not_called()


# ---------------------------------------------------------------------------
# _decide_synchronize_review_mode
# ---------------------------------------------------------------------------


class TestDecideSynchronizeReviewMode:
    @pytest.mark.asyncio
    async def test_returns_scoped_when_llm_says_scoped(self):
        from baloo.review.orchestrator import _decide_synchronize_review_mode

        with patch(
            "baloo.review.orchestrator.PIAgentBase.run_query",
            new=AsyncMock(return_value=({"mode": "scoped", "reason": "small diff"}, {})),
        ):
            mode, reason = await _decide_synchronize_review_mode(
                pr_context=_make_pr_context(),
                changed_files_changed=[],
                scoped_diff="+ small change",
            )

        assert mode == "scoped"
        assert reason == "small diff"

    @pytest.mark.asyncio
    async def test_returns_full_pr_when_llm_says_full_pr(self):
        from baloo.review.orchestrator import _decide_synchronize_review_mode

        with patch(
            "baloo.review.orchestrator.PIAgentBase.run_query",
            new=AsyncMock(return_value=({"mode": "full_pr", "reason": "large refactor"}, {})),
        ):
            mode, _ = await _decide_synchronize_review_mode(
                pr_context=_make_pr_context(),
                changed_files_changed=[],
                scoped_diff="+ many changes",
            )

        assert mode == "full_pr"

    @pytest.mark.asyncio
    async def test_returns_full_pr_on_unexpected_mode(self):
        from baloo.review.orchestrator import _decide_synchronize_review_mode

        with patch(
            "baloo.review.orchestrator.PIAgentBase.run_query",
            new=AsyncMock(return_value=({"mode": "unknown_mode"}, {})),
        ):
            mode, _ = await _decide_synchronize_review_mode(
                pr_context=_make_pr_context(),
                changed_files_changed=[],
                scoped_diff="",
            )

        assert mode == "full_pr"

    @pytest.mark.asyncio
    async def test_returns_full_pr_on_exception(self):
        from baloo.review.orchestrator import _decide_synchronize_review_mode

        with patch(
            "baloo.review.orchestrator.PIAgentBase.run_query",
            new=AsyncMock(side_effect=RuntimeError("LLM timeout")),
        ):
            mode, reason = await _decide_synchronize_review_mode(
                pr_context=_make_pr_context(),
                changed_files_changed=[],
                scoped_diff="",
            )

        assert mode == "full_pr"


# ---------------------------------------------------------------------------
# Scope preparation exception
# ---------------------------------------------------------------------------


class TestScopePreparationException:
    @pytest.mark.asyncio
    async def test_scope_prep_exception_falls_back_to_full_pr(self):
        """When get_changed_scope_between_commits raises, falls back to full PR review."""
        gc = _make_github_client()
        gc.get_changed_scope_between_commits = AsyncMock(side_effect=RuntimeError("diff failed"))
        agent = _make_agent()

        await _run_review(
            gc,
            agent,
            trigger_reason="pull_request:synchronize",
            synchronize_base_sha="base123",
        )

        agent.review_pr.assert_called_once()


# ---------------------------------------------------------------------------
# Thread deduplication
# ---------------------------------------------------------------------------


def _make_thread(
    *,
    thread_id: int = 1,
    path: str = "file.py",
    line: int = 10,
    body: str = "**[HIGH] Bugs** - **null check missing**\n\nYou should add null checks",
    resolved: bool = False,
    outdated: bool = False,
    awaiting_response: bool = False,
    is_baloo_thread: bool = True,
) -> DiscussionThread:
    now = _now()
    return DiscussionThread(
        id=thread_id,
        path=path,
        line=line,
        comments=[
            DiscussionComment(
                id=thread_id,
                author="baloo-code-reviewer[bot]",
                body=body,
                created_at=now,
                updated_at=now,
                source="review_comment",
                is_baloo=is_baloo_thread,
                path=path,
                line=line,
            )
        ],
        is_baloo_thread=is_baloo_thread,
        awaiting_response=awaiting_response,
        resolved=resolved,
        outdated=outdated,
        last_activity=now,
        root_comment_id=thread_id,
    )


class TestThreadDeduplication:
    @pytest.mark.asyncio
    async def test_resolved_thread_matching_finding_is_skipped(self):
        """A finding that matches a resolved thread should not be re-posted as blocking."""
        body = "**[HIGH] Bugs** - **null check missing**\n\nYou should add null checks"
        thread = _make_thread(resolved=True, body=body)
        gc = _make_github_client()
        gc.get_pr_context = AsyncMock(return_value=_make_pr_context(threads=[thread]))
        comment = ReviewComment(
            path="file.py",
            line=10,
            body=body,
            severity=ReviewSeverity.HIGH,
            category=FindingCategory.BUGS,
        )
        # Agent says request_changes but the matching resolved thread causes the
        # finding to be dropped — so the orchestrator ends up approving.
        agent = _make_agent(comments=[comment], approve=True, request_changes=False)

        await _run_review(gc, agent)

        # Approval review IS posted (finding was skipped), but no blocking review
        calls = gc.post_review.call_args_list
        for call in calls:
            result_arg = call.args[2] if len(call.args) >= 3 else call.kwargs.get("review_result")
            assert not (
                result_arg and result_arg.request_changes
            ), "Should not post a request_changes review when the only finding is resolved"

    @pytest.mark.asyncio
    async def test_outdated_thread_matching_finding_is_skipped(self):
        """A finding that matches an outdated thread should not be re-posted as blocking."""
        body = "**[HIGH] Bugs** - **null check missing**\n\nYou should add null checks"
        thread = _make_thread(outdated=True, body=body)
        gc = _make_github_client()
        gc.get_pr_context = AsyncMock(return_value=_make_pr_context(threads=[thread]))
        comment = ReviewComment(
            path="file.py",
            line=10,
            body=body,
            severity=ReviewSeverity.HIGH,
            category=FindingCategory.BUGS,
        )
        agent = _make_agent(comments=[comment], approve=True, request_changes=False)

        await _run_review(gc, agent)

        calls = gc.post_review.call_args_list
        for call in calls:
            result_arg = call.args[2] if len(call.args) >= 3 else call.kwargs.get("review_result")
            assert not (
                result_arg and result_arg.request_changes
            ), "Should not post a request_changes review when the only finding is outdated"

    @pytest.mark.asyncio
    async def test_awaiting_response_thread_matching_finding_is_skipped(self):
        """A finding that matches an awaiting-response thread should not be re-posted."""
        body = "**[HIGH] Bugs** - **null check missing**\n\nYou should add null checks"
        thread = _make_thread(awaiting_response=True, body=body)
        gc = _make_github_client()
        gc.get_pr_context = AsyncMock(return_value=_make_pr_context(threads=[thread]))
        comment = ReviewComment(
            path="file.py",
            line=10,
            body=body,
            severity=ReviewSeverity.HIGH,
            category=FindingCategory.BUGS,
        )
        agent = _make_agent(comments=[comment], approve=True, request_changes=False)

        await _run_review(gc, agent)

        calls = gc.post_review.call_args_list
        for call in calls:
            result_arg = call.args[2] if len(call.args) >= 3 else call.kwargs.get("review_result")
            assert not (
                result_arg and result_arg.request_changes
            ), "Should not post a request_changes review when the only finding is awaiting response"


# ---------------------------------------------------------------------------
# DB update on successful review
# ---------------------------------------------------------------------------


class TestDbUpdateOnSuccessfulReview:
    async def _run_with_db(self, agent, gc, db_review_id=99):
        from baloo.review.orchestrator import process_pr_review

        mock_complete = AsyncMock()

        with ExitStack() as stack:
            for p in _base_patches(gc, agent):
                stack.enter_context(p)
            # override: database_enabled must be True for DB tests
            stack.enter_context(patch("baloo.review.orchestrator.settings.database_enabled", True))
            stack.enter_context(patch("baloo.config.settings.settings.database_enabled", True))
            stack.enter_context(
                patch(
                    "baloo.review.orchestrator.ReviewService.start_review",
                    new=AsyncMock(return_value=db_review_id),
                )
            )
            stack.enter_context(
                patch("baloo.review.orchestrator.ReviewService.complete_review", new=mock_complete)
            )
            stack.enter_context(
                patch(
                    "baloo.review.orchestrator.ReviewService.is_review_cancelled",
                    new=AsyncMock(return_value=False),
                )
            )
            await process_pr_review(
                repo_full_name="org/repo",
                pr_number=1,
                installation_id=1,
                trigger_reason="pull_request:opened",
                notify_progress=False,
                head_sha="abc123",
            )
        return mock_complete

    @pytest.mark.asyncio
    async def test_approved_review_sets_approved_status(self):
        gc = _make_github_client()
        agent = _make_agent(approve=True, request_changes=False)
        mock_complete = await self._run_with_db(agent, gc)

        mock_complete.assert_called_once()
        data = mock_complete.call_args.kwargs["data"]
        assert data.review_status == "approved"

    @pytest.mark.asyncio
    async def test_agent_error_sets_agent_error_status(self):
        gc = _make_github_client()
        agent = _make_agent(
            approve=False,
            request_changes=False,
            metadata={"agent_error": True, "error_detail": "timeout"},
        )
        mock_complete = await self._run_with_db(agent, gc)

        mock_complete.assert_called_once()
        data = mock_complete.call_args.kwargs["data"]
        assert data.review_status == "agent_error"


# ---------------------------------------------------------------------------
# CancelledError and general exception handling
# ---------------------------------------------------------------------------


class TestProcessPrReviewExceptionHandling:
    @pytest.mark.asyncio
    async def test_cancelled_error_updates_db_and_reraises(self):
        from baloo.review.orchestrator import process_pr_review

        gc = _make_github_client()
        gc.get_pr_context = AsyncMock(side_effect=asyncio.CancelledError())
        mock_complete = AsyncMock()

        with ExitStack() as stack:
            stack.enter_context(patch("baloo.review.orchestrator.GitHubAPIClient", return_value=gc))
            stack.enter_context(patch("baloo.review.orchestrator.settings.fidelity_enabled", False))
            stack.enter_context(
                patch("baloo.review.orchestrator.settings.fp_verification_enabled", False)
            )
            stack.enter_context(patch("baloo.review.orchestrator.settings.database_enabled", True))
            stack.enter_context(patch("baloo.config.settings.settings.database_enabled", True))
            stack.enter_context(
                patch("baloo.review.orchestrator.settings.feedback_signals_enabled", False)
            )
            stack.enter_context(
                patch("baloo.review.orchestrator.settings.review_use_checks_api", False)
            )
            stack.enter_context(
                patch(
                    "baloo.review.orchestrator.ReviewService.start_review",
                    new=AsyncMock(return_value=7),
                )
            )
            stack.enter_context(
                patch("baloo.review.orchestrator.ReviewService.complete_review", new=mock_complete)
            )
            stack.enter_context(
                patch(
                    "baloo.review.orchestrator.ReviewService.is_review_cancelled",
                    new=AsyncMock(return_value=False),
                )
            )

            with pytest.raises(asyncio.CancelledError):
                await process_pr_review(
                    repo_full_name="org/repo",
                    pr_number=1,
                    installation_id=1,
                    trigger_reason="pull_request:opened",
                    notify_progress=False,
                    head_sha="abc123",
                )

        mock_complete.assert_called_once()
        data = mock_complete.call_args.kwargs["data"]
        assert data.review_status == "cancelled"

    @pytest.mark.asyncio
    async def test_general_exception_updates_db_with_error_status(self):
        from baloo.review.orchestrator import process_pr_review

        gc = _make_github_client()
        gc.get_pr_context = AsyncMock(side_effect=RuntimeError("unexpected crash"))
        mock_complete = AsyncMock()

        with ExitStack() as stack:
            stack.enter_context(patch("baloo.review.orchestrator.GitHubAPIClient", return_value=gc))
            stack.enter_context(patch("baloo.review.orchestrator.settings.fidelity_enabled", False))
            stack.enter_context(
                patch("baloo.review.orchestrator.settings.fp_verification_enabled", False)
            )
            stack.enter_context(patch("baloo.review.orchestrator.settings.database_enabled", True))
            stack.enter_context(patch("baloo.config.settings.settings.database_enabled", True))
            stack.enter_context(
                patch("baloo.review.orchestrator.settings.feedback_signals_enabled", False)
            )
            stack.enter_context(
                patch("baloo.review.orchestrator.settings.review_use_checks_api", False)
            )
            stack.enter_context(
                patch(
                    "baloo.review.orchestrator.ReviewService.start_review",
                    new=AsyncMock(return_value=8),
                )
            )
            stack.enter_context(
                patch("baloo.review.orchestrator.ReviewService.complete_review", new=mock_complete)
            )
            stack.enter_context(
                patch(
                    "baloo.review.orchestrator.ReviewService.is_review_cancelled",
                    new=AsyncMock(return_value=False),
                )
            )

            await process_pr_review(
                repo_full_name="org/repo",
                pr_number=1,
                installation_id=1,
                trigger_reason="pull_request:opened",
                notify_progress=False,
                head_sha="abc123",
            )

        mock_complete.assert_called_once()
        data = mock_complete.call_args.kwargs["data"]
        assert data.review_status == "error"


# ---------------------------------------------------------------------------
# GitHub Checks API + fallback
# ---------------------------------------------------------------------------


class TestGitHubChecksApiPath:
    @pytest.mark.asyncio
    async def test_medium_findings_posted_as_check_when_checks_enabled(self):
        from baloo.review.orchestrator import process_pr_review

        gc = _make_github_client()
        medium_comment = ReviewComment(
            path="app.py",
            line=5,
            body="**[MEDIUM] Quality** - **minor issue**\n\nsuggestion",
            severity=ReviewSeverity.MEDIUM,
            category=FindingCategory.QUALITY,
        )
        agent = _make_agent(comments=[medium_comment], approve=True, request_changes=False)

        mock_checks_client = AsyncMock()
        mock_checks_client.__aenter__ = AsyncMock(return_value=mock_checks_client)
        mock_checks_client.__aexit__ = AsyncMock(return_value=False)
        mock_checks_client.create_check_run = AsyncMock(return_value=99)
        mock_checks_client.add_annotations = AsyncMock()

        with ExitStack() as stack:
            for p in _base_patches(gc, agent):
                stack.enter_context(p)
            # Override the review_use_checks_api patch to True
            stack.enter_context(
                patch("baloo.review.orchestrator.settings.review_use_checks_api", True)
            )
            # Local import in orchestrator — patch the source module, not orchestrator namespace
            stack.enter_context(
                patch("baloo.github.checks_api.GitHubChecksClient", return_value=mock_checks_client)
            )
            await process_pr_review(
                repo_full_name="org/repo",
                pr_number=1,
                installation_id=1,
                notify_progress=False,
                head_sha="abc123",
            )

        mock_checks_client.create_check_run.assert_called_once()
        mock_checks_client.add_annotations.assert_called_once()

    @pytest.mark.asyncio
    async def test_checks_api_failure_falls_back_to_issue_comments(self):
        from baloo.review.orchestrator import process_pr_review

        gc = _make_github_client()
        medium_comment = ReviewComment(
            path="app.py",
            line=5,
            body="**[MEDIUM] Quality** - **minor issue**\n\nsuggestion",
            severity=ReviewSeverity.MEDIUM,
            category=FindingCategory.QUALITY,
        )
        agent = _make_agent(comments=[medium_comment], approve=True, request_changes=False)

        mock_checks_client = AsyncMock()
        mock_checks_client.__aenter__ = AsyncMock(return_value=mock_checks_client)
        mock_checks_client.__aexit__ = AsyncMock(return_value=False)
        mock_checks_client.create_check_run = AsyncMock(
            side_effect=RuntimeError("checks unavailable")
        )

        with ExitStack() as stack:
            for p in _base_patches(gc, agent):
                stack.enter_context(p)
            stack.enter_context(
                patch("baloo.review.orchestrator.settings.review_use_checks_api", True)
            )
            # Local import in orchestrator — patch the source module, not orchestrator namespace
            stack.enter_context(
                patch("baloo.github.checks_api.GitHubChecksClient", return_value=mock_checks_client)
            )
            await process_pr_review(
                repo_full_name="org/repo",
                pr_number=1,
                installation_id=1,
                notify_progress=False,
                head_sha="abc123",
            )

        # Fallback: posted as issue comment
        gc.post_comment.assert_called()
