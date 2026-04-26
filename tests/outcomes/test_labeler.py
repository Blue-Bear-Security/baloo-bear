"""Tests for outcome labeler."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from baloo.db.engine import reset_engine
from baloo.db.models import Base, Finding, FindingOutcome, Review
from baloo.outcomes.labeler import determine_outcome, label_pr_outcomes

# ---------------------------------------------------------------------------
# determine_outcome — pure priority logic
# ---------------------------------------------------------------------------


class TestDetermineOutcome:
    def test_actioned_wins_over_everything(self):
        signals = {
            "code_changed_near_line": True,
            "reply_sentiment": "negative",
            "developer_replied": True,
            "thread_resolved": True,
        }
        assert determine_outcome(signals) == "actioned"

    def test_actioned_minimal_signals(self):
        signals = {
            "code_changed_near_line": True,
            "reply_sentiment": None,
            "developer_replied": False,
            "thread_resolved": False,
        }
        assert determine_outcome(signals) == "actioned"

    def test_disputed_when_negative_sentiment(self):
        signals = {
            "code_changed_near_line": False,
            "reply_sentiment": "negative",
            "developer_replied": True,
            "thread_resolved": False,
        }
        assert determine_outcome(signals) == "disputed"

    def test_acknowledged_positive_reply(self):
        signals = {
            "code_changed_near_line": False,
            "reply_sentiment": "positive",
            "developer_replied": True,
            "thread_resolved": False,
        }
        assert determine_outcome(signals) == "acknowledged"

    def test_acknowledged_thread_resolved(self):
        signals = {
            "code_changed_near_line": False,
            "reply_sentiment": "neutral",
            "developer_replied": True,
            "thread_resolved": True,
        }
        assert determine_outcome(signals) == "acknowledged"

    def test_ignored_no_signals(self):
        signals = {
            "code_changed_near_line": False,
            "reply_sentiment": None,
            "developer_replied": False,
            "thread_resolved": False,
        }
        assert determine_outcome(signals) == "ignored"

    def test_ignored_neutral_reply_not_resolved(self):
        signals = {
            "code_changed_near_line": False,
            "reply_sentiment": "neutral",
            "developer_replied": True,
            "thread_resolved": False,
        }
        assert determine_outcome(signals) == "ignored"

    def test_ignored_no_dev_reply_but_resolved(self):
        """Thread resolved without dev reply doesn't count as acknowledged."""
        signals = {
            "code_changed_near_line": False,
            "reply_sentiment": None,
            "developer_replied": False,
            "thread_resolved": True,
        }
        assert determine_outcome(signals) == "ignored"


# ---------------------------------------------------------------------------
# label_pr_outcomes — DB integration tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_factory():
    reset_engine()
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    with patch("baloo.outcomes.labeler.get_session_factory", return_value=factory):
        yield factory
    await engine.dispose()
    reset_engine()


async def _seed_review_with_findings(factory, *, count=2) -> tuple[Review, list[Finding]]:
    """Insert a review with findings and return them."""
    async with factory() as session:
        async with session.begin():
            review = Review(
                repo_full_name="owner/repo",
                pr_number=42,
                pr_title="Test PR",
                pr_author="dev",
                commit_sha="abc123",
                review_status="commented",
                trigger_reason="push",
                started_at=datetime.now(timezone.utc),
            )
            session.add(review)
            await session.flush()

            findings = []
            for i in range(count):
                f = Finding(
                    review_id=review.id,
                    file_path=f"src/file{i}.py",
                    line_number=10 + i,
                    severity="medium",
                    category="Quality",
                    body=f"Finding {i}",
                )
                session.add(f)
                findings.append(f)
            await session.flush()

    return review, findings


def _mock_merge_signals(threads=None):
    """Return an AsyncMock for fetch_merge_signals."""
    diff = """\
diff --git a/src/file0.py b/src/file0.py
--- a/src/file0.py
+++ b/src/file0.py
@@ -8,6 +8,7 @@
 ctx
 ctx
+changed line at 10
 ctx
"""
    if threads is None:
        threads = []
    mock = AsyncMock(return_value=(diff, threads))
    return mock


@pytest.mark.asyncio
async def test_label_pr_outcomes_creates_rows(db_factory):
    review, findings = await _seed_review_with_findings(db_factory)

    # Thread matches file0.py line 10 with a positive dev reply
    threads = [
        {
            "path": "src/file0.py",
            "line": 10,
            "is_resolved": False,
            "comments": [
                {"author": "baloo[bot]", "body": "issue here", "is_baloo": True},
                {"author": "dev", "body": "good catch, fixed", "is_baloo": False},
            ],
        }
    ]

    diff = _mock_merge_signals().return_value[0]
    mock_fetch = AsyncMock(return_value=(diff, threads))

    with patch("baloo.outcomes.labeler.fetch_merge_signals", mock_fetch):
        await label_pr_outcomes("owner/repo", 42, 12345)

    # Verify outcomes were created
    async with db_factory() as session:
        from sqlalchemy import select

        rows = (await session.execute(select(FindingOutcome))).scalars().all()
        assert len(rows) == 2

        outcomes_by_finding = {r.finding_id: r for r in rows}

        # file0.py had code change near line 10 → actioned
        f0 = outcomes_by_finding[findings[0].id]
        assert f0.outcome == "actioned"
        assert f0.repo_full_name == "owner/repo"
        assert f0.pr_number == 42

        # file1.py had no matching thread and no code change → ignored
        f1 = outcomes_by_finding[findings[1].id]
        assert f1.outcome == "ignored"


@pytest.mark.asyncio
async def test_label_pr_outcomes_skips_when_no_findings(db_factory):
    """No findings → log and return without calling fetch_merge_signals."""
    with patch("baloo.outcomes.labeler.fetch_merge_signals", new_callable=AsyncMock) as mock_fetch:
        await label_pr_outcomes("owner/repo", 99, 12345)
        mock_fetch.assert_not_called()


@pytest.mark.asyncio
async def test_label_pr_outcomes_idempotent(db_factory):
    """Running twice doesn't duplicate FindingOutcome rows."""
    review, findings = await _seed_review_with_findings(db_factory, count=1)

    mock_fetch = AsyncMock(
        return_value=(
            _mock_merge_signals().return_value[0],
            [],
        )
    )

    with patch("baloo.outcomes.labeler.fetch_merge_signals", mock_fetch):
        await label_pr_outcomes("owner/repo", 42, 12345)
        await label_pr_outcomes("owner/repo", 42, 12345)

    async with db_factory() as session:
        from sqlalchemy import select

        rows = (await session.execute(select(FindingOutcome))).scalars().all()
        assert len(rows) == 1
