"""Tests for SQLAlchemy ORM models."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from baloo.db.models import Base, Finding, FindingOutcome, Review, ReviewLog


@pytest.fixture
async def async_session():
    """Create an in-memory SQLite async session for testing."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


async def test_create_review(async_session: AsyncSession):
    """Test creating a Review record."""
    review = Review(
        repo_full_name="owner/repo",
        pr_number=42,
        pr_title="Add feature X",
        pr_author="alice",
        commit_sha="abc123def456",
        review_status="approved",
        trigger_reason="pull_request:opened",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
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
    )
    async with async_session.begin():
        async_session.add(review)

    result = await async_session.execute(select(Review))
    saved = result.scalar_one()
    assert saved.repo_full_name == "owner/repo"
    assert saved.pr_number == 42
    assert saved.pr_title == "Add feature X"
    assert saved.review_status == "approved"
    assert saved.tokens_input == 1000
    assert saved.auto_approved is True
    assert saved.fidelity_score == 95.0


async def test_create_finding(async_session: AsyncSession):
    """Test creating a Finding linked to a Review."""
    review = Review(
        repo_full_name="owner/repo",
        pr_number=10,
        review_status="changes_requested",
        trigger_reason="pull_request:synchronize",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    async with async_session.begin():
        async_session.add(review)

    finding = Finding(
        review_id=review.id,
        file_path="src/main.py",
        line_number=42,
        severity="HIGH",
        category="Security",
        body="SQL injection risk in user input handling",
    )
    async with async_session.begin():
        async_session.add(finding)

    result = await async_session.execute(select(Finding))
    saved = result.scalar_one()
    assert saved.file_path == "src/main.py"
    assert saved.line_number == 42
    assert saved.severity == "HIGH"
    assert saved.category == "Security"
    assert saved.review_id == review.id


async def test_review_findings_relationship(async_session: AsyncSession):
    """Test the relationship between Review and Finding."""
    review = Review(
        repo_full_name="owner/repo",
        pr_number=20,
        review_status="changes_requested",
        trigger_reason="pull_request:opened",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    finding1 = Finding(file_path="a.py", severity="HIGH", category="Bugs", body="Null pointer")
    finding2 = Finding(
        file_path="b.py", severity="LOW", category="Quality", body="Missing docstring"
    )
    review.findings = [finding1, finding2]

    async with async_session.begin():
        async_session.add(review)

    result = await async_session.execute(select(Review).where(Review.id == review.id))
    saved = result.scalar_one()
    await async_session.refresh(saved, ["findings"])
    assert len(saved.findings) == 2
    severities = {f.severity for f in saved.findings}
    assert severities == {"HIGH", "LOW"}


async def test_cascade_delete(async_session: AsyncSession):
    """Test that deleting a Review cascades to its Findings."""
    review = Review(
        repo_full_name="owner/repo",
        pr_number=30,
        review_status="approved",
        trigger_reason="pull_request:opened",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    review.findings = [
        Finding(file_path="x.py", severity="MEDIUM", category="Quality", body="Issue")
    ]
    async with async_session.begin():
        async_session.add(review)

    review_id = review.id

    async with async_session.begin():
        to_delete = await async_session.get(Review, review_id)
        await async_session.delete(to_delete)

    result = await async_session.execute(select(Finding).where(Finding.review_id == review_id))
    assert result.scalars().all() == []


def test_review_log_model_fields():
    """ReviewLog has all expected columns."""
    from sqlalchemy import inspect

    mapper = inspect(ReviewLog)
    columns = {c.key for c in mapper.columns}
    assert columns == {
        "id",
        "review_id",
        "created_at",
        "event_type",
        "message",
        "raw_text",
        "metadata_json",
    }


def test_finding_outcome_model_exists():
    """FindingOutcome has expected columns."""
    outcome = FindingOutcome(
        finding_id=1,
        review_id=1,
        repo_full_name="owner/repo",
        pr_number=42,
        outcome="actioned",
        signals={"code_changed_near_line": True},
    )
    assert outcome.outcome == "actioned"
    assert outcome.signals == {"code_changed_near_line": True}
    assert outcome.repo_full_name == "owner/repo"


async def test_review_optional_fields(async_session: AsyncSession):
    """Test creating a Review with only required fields."""
    review = Review(
        repo_full_name="owner/repo",
        pr_number=1,
        review_status="error",
        trigger_reason="pull_request:opened",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        error_message="Something went wrong",
    )
    async with async_session.begin():
        async_session.add(review)

    result = await async_session.execute(select(Review))
    saved = result.scalar_one()
    assert saved.completed_at is None
    assert saved.duration_seconds is None
    assert saved.model_used is None
    assert saved.tokens_input is None
    assert saved.cost_usd is None
    assert saved.error_message == "Something went wrong"
