"""Tests for ReviewService."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from baloo.db.engine import reset_engine
from baloo.db.models import Base, Finding, Review
from baloo.db.service import (
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

    reset_engine()


def test_settings_installation_id_defaults_to_none():
    from baloo.config.settings import get_settings

    settings = get_settings()
    assert settings.installation_id is None


def test_settings_installation_id_from_env(monkeypatch):
    from baloo.config.settings import get_settings, reset_settings

    monkeypatch.setenv("INSTALLATION_ID", "inst_abc123")
    reset_settings()
    settings = get_settings()
    assert settings.installation_id == "inst_abc123"
    reset_settings()


async def test_start_review_sets_installation_id(db_session_factory, monkeypatch):
    """Test that start_review populates installation_id from settings."""
    monkeypatch.setenv("INSTALLATION_ID", "inst_xyz")
    from baloo.config.settings import reset_settings

    reset_settings()

    review_id = await ReviewService.start_review(
        repo_full_name="owner/repo",
        pr_number=99,
        trigger_reason="pull_request:opened",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    async with db_session_factory() as session:
        review = await session.get(Review, review_id)
        assert review.installation_id == "inst_xyz"
    reset_settings()


async def test_start_review_installation_id_none_when_unset(db_session_factory):
    """Test that start_review sets installation_id to None when not configured."""
    review_id = await ReviewService.start_review(
        repo_full_name="owner/repo",
        pr_number=100,
        trigger_reason="pull_request:opened",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    async with db_session_factory() as session:
        review = await session.get(Review, review_id)
        assert review.installation_id is None


async def test_complete_review_sets_installation_id_on_findings(db_session_factory, monkeypatch):
    """Test that complete_review populates installation_id on findings."""
    monkeypatch.setenv("INSTALLATION_ID", "inst_xyz")
    from baloo.config.settings import reset_settings

    reset_settings()

    review_id = await ReviewService.start_review(
        repo_full_name="owner/repo",
        pr_number=101,
        trigger_reason="pull_request:opened",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    await ReviewService.complete_review(
        review_id=review_id,
        data=ReviewCompleteDTO(
            review_status="approved",
            findings=[
                {
                    "file_path": "x.py",
                    "line_number": 1,
                    "severity": "HIGH",
                    "category": "Security",
                    "body": "test finding",
                }
            ],
        ),
    )

    async with db_session_factory() as session:
        result = await session.execute(select(Finding).where(Finding.review_id == review_id))
        findings = result.scalars().all()
        assert all(f.installation_id == "inst_xyz" for f in findings)
    reset_settings()
