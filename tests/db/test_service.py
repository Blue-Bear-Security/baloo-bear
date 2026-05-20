"""Tests for ReviewService."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from baloo.db.engine import reset_engine
from baloo.db.models import Base, Finding, Review
from baloo.db.service import (
    DuplicateReviewError,
    ReviewCompleteDTO,
    ReviewNotFoundError,
    ReviewService,
    ReviewServiceError,
)


@pytest.fixture
async def db_session_factory():
    """Set up an in-memory SQLite database and patch the session factory."""
    reset_engine()

    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)

    with patch("baloo.db.service.get_session_factory", return_value=factory):
        yield factory

    await engine.dispose()
    reset_engine()


async def test_start_review(db_session_factory):
    """Test creating an in-progress review row."""
    review_id = await ReviewService.start_review(
        repo_full_name="owner/repo",
        pr_number=42,
        commit_sha="abc123",
        trigger_reason="pull_request:opened",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert review_id is not None

    async with db_session_factory() as session:
        review = await session.get(Review, review_id)
        assert review.repo_full_name == "owner/repo"
        assert review.pr_number == 42
        assert review.review_status == "in_progress"
        assert review.completed_at is None
        assert review.tokens_input is None


async def test_start_review_exception_raises_error():
    """Test that start_review raises ReviewServiceError on database errors."""
    reset_engine()

    with patch(
        "baloo.db.service.get_session_factory",
        side_effect=Exception("Connection refused"),
    ):
        with pytest.raises(ReviewServiceError):
            await ReviewService.start_review(
                repo_full_name="owner/repo",
                pr_number=1,
                commit_sha="abc123",
                trigger_reason="pull_request:opened",
                started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )

    reset_engine()


async def test_complete_review_success(db_session_factory):
    """Test completing a review with findings."""
    # Start a review first
    review_id = await ReviewService.start_review(
        repo_full_name="owner/repo",
        pr_number=42,
        commit_sha="abc123",
        trigger_reason="pull_request:opened",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert review_id is not None

    # Complete it
    complete_data = ReviewCompleteDTO(
        pr_title="Add feature",
        pr_author="alice",
        commit_sha="abc123",
        review_status="approved",
        completed_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        duration_seconds=60.0,
        model_used="sonnet",
        tokens_input=1000,
        tokens_output=500,
        cost_usd=0.01,
        agent_turns=3,
        files_examined=5,
        auto_approved=True,
        fidelity_score=95.0,
        findings=[
            {
                "file_path": "src/main.py",
                "line_number": 10,
                "severity": "HIGH",
                "category": "Security",
                "body": "SQL injection risk",
            },
            {
                "file_path": "src/utils.py",
                "line_number": 25,
                "severity": "LOW",
                "category": "Quality",
                "body": "Consider renaming variable",
            },
        ],
    )
    await ReviewService.complete_review(
        review_id=review_id,
        data=complete_data,
    )

    async with db_session_factory() as session:
        review = await session.get(Review, review_id)
        assert review.review_status == "approved"
        assert review.pr_title == "Add feature"
        assert review.tokens_input == 1000

        result = await session.execute(select(Finding).where(Finding.review_id == review_id))
        findings = result.scalars().all()
        assert len(findings) == 2


async def test_complete_review_error_status(db_session_factory):
    """Test completing a review with error status."""
    review_id = await ReviewService.start_review(
        repo_full_name="owner/repo",
        pr_number=1,
        commit_sha="abc123",
        trigger_reason="pull_request:opened",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    complete_data = ReviewCompleteDTO(
        review_status="error",
        completed_at=datetime(2026, 1, 1, 0, 0, 30, tzinfo=timezone.utc),
        duration_seconds=30.0,
        error_message="Something failed",
    )
    await ReviewService.complete_review(
        review_id=review_id,
        data=complete_data,
    )

    async with db_session_factory() as session:
        review = await session.get(Review, review_id)
        assert review.review_status == "error"
        assert review.error_message == "Something failed"
        assert review.tokens_input is None


async def test_complete_review_not_found(db_session_factory):
    """Test completing a non-existent review raises ReviewNotFoundError."""
    complete_data = ReviewCompleteDTO(review_status="approved")
    with pytest.raises(ReviewNotFoundError):
        await ReviewService.complete_review(
            review_id=99999,
            data=complete_data,
        )


async def test_complete_review_no_findings(db_session_factory):
    """Test completing a review without findings."""
    review_id = await ReviewService.start_review(
        repo_full_name="owner/repo",
        pr_number=5,
        commit_sha="abc123",
        trigger_reason="pull_request:opened",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    complete_data = ReviewCompleteDTO(
        pr_title="Clean PR",
        pr_author="bob",
        commit_sha="def456",
        review_status="approved",
    )
    await ReviewService.complete_review(
        review_id=review_id,
        data=complete_data,
    )

    async with db_session_factory() as session:
        result = await session.execute(select(Finding).where(Finding.review_id == review_id))
        assert result.scalars().all() == []


async def test_complete_review_exception_raises_error():
    """Test that complete_review raises ReviewServiceError on database errors."""
    reset_engine()

    complete_data = ReviewCompleteDTO(review_status="error")
    with patch(
        "baloo.db.service.get_session_factory",
        side_effect=Exception("Connection refused"),
    ):
        with pytest.raises(ReviewServiceError):
            await ReviewService.complete_review(
                review_id=1,
                data=complete_data,
            )


async def test_start_review_duplicate_sha_raises_error(db_session_factory):
    """Two replicas reviewing the same commit SHA raise DuplicateReviewError on the second."""
    await ReviewService.start_review(
        repo_full_name="owner/repo",
        pr_number=10,
        commit_sha="abc123",
        trigger_reason="pull_request:opened",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    with pytest.raises(DuplicateReviewError):
        await ReviewService.start_review(
            repo_full_name="owner/repo",
            pr_number=10,
            commit_sha="abc123",
            trigger_reason="pull_request:opened",
            started_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
        )


async def test_start_review_new_commit_cancels_old_sha(db_session_factory):
    """A new commit (different SHA) cancels any in-progress review for the same PR."""
    old_id = await ReviewService.start_review(
        repo_full_name="owner/repo",
        pr_number=10,
        commit_sha="abc123",
        trigger_reason="pull_request:opened",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    new_id = await ReviewService.start_review(
        repo_full_name="owner/repo",
        pr_number=10,
        commit_sha="def456",
        trigger_reason="pull_request:synchronize",
        started_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
    )
    assert new_id != old_id

    async with db_session_factory() as session:
        old_review = await session.get(Review, old_id)
        assert old_review.review_status == "cancelled"
        new_review = await session.get(Review, new_id)
        assert new_review.review_status == "in_progress"


async def test_start_review_same_sha_does_not_cancel_existing(db_session_factory):
    """Duplicate webhook for the same SHA does not cancel the running review."""
    running_id = await ReviewService.start_review(
        repo_full_name="owner/repo",
        pr_number=10,
        commit_sha="abc123",
        trigger_reason="pull_request:opened",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(DuplicateReviewError):
        await ReviewService.start_review(
            repo_full_name="owner/repo",
            pr_number=10,
            commit_sha="abc123",
            trigger_reason="pull_request:opened",
            started_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
        )

    async with db_session_factory() as session:
        review = await session.get(Review, running_id)
        assert review.review_status == "in_progress"


async def test_is_review_cancelled(db_session_factory):
    """is_review_cancelled returns True after the review is cancelled."""
    review_id = await ReviewService.start_review(
        repo_full_name="owner/repo",
        pr_number=10,
        commit_sha="abc123",
        trigger_reason="pull_request:opened",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert not await ReviewService.is_review_cancelled(review_id)

    # A new commit cancels it
    await ReviewService.start_review(
        repo_full_name="owner/repo",
        pr_number=10,
        commit_sha="def456",
        trigger_reason="pull_request:synchronize",
        started_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
    )
    assert await ReviewService.is_review_cancelled(review_id)


async def test_start_review_stale_sha_allows_retry(db_session_factory):
    """A stale in-progress review for the same SHA is cleared, allowing a retry."""
    from datetime import timedelta

    old_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    old_id = await ReviewService.start_review(
        repo_full_name="owner/repo",
        pr_number=20,
        commit_sha="abc123",
        trigger_reason="pull_request:opened",
        started_at=old_start,
    )

    new_start = old_start + timedelta(hours=2)
    new_id = await ReviewService.start_review(
        repo_full_name="owner/repo",
        pr_number=20,
        commit_sha="abc123",
        trigger_reason="pull_request:opened",
        started_at=new_start,
    )
    assert new_id is not None
    assert new_id != old_id

    async with db_session_factory() as session:
        old_review = await session.get(Review, old_id)
        assert old_review.review_status == "error"
        new_review = await session.get(Review, new_id)
        assert new_review.review_status == "in_progress"


async def test_start_review_different_prs_allowed(db_session_factory):
    """Concurrent in-progress reviews for different PRs are allowed."""
    id1 = await ReviewService.start_review(
        repo_full_name="owner/repo",
        pr_number=30,
        commit_sha="abc123",
        trigger_reason="pull_request:opened",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    id2 = await ReviewService.start_review(
        repo_full_name="owner/repo",
        pr_number=31,
        commit_sha="abc123",
        trigger_reason="pull_request:opened",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert id1 != id2


async def test_start_review_after_completion_allows_retry(db_session_factory):
    """The same SHA can be reviewed again after the previous review completes."""
    review_id = await ReviewService.start_review(
        repo_full_name="owner/repo",
        pr_number=40,
        commit_sha="abc123",
        trigger_reason="pull_request:opened",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    await ReviewService.complete_review(
        review_id=review_id,
        data=ReviewCompleteDTO(review_status="approved"),
    )

    new_id = await ReviewService.start_review(
        repo_full_name="owner/repo",
        pr_number=40,
        commit_sha="abc123",
        trigger_reason="pull_request:opened",
        started_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
    )
    assert new_id is not None
    assert new_id != review_id

    reset_engine()
