"""Tests for the feedback signal service."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from baloo.db.engine import reset_engine
from baloo.db.feedback_service import FeedbackService
from baloo.db.models import Base, FeedbackSignal


@pytest.fixture
def mock_session():
    """Create a mock async session."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock()
    session.begin.return_value.__aenter__ = AsyncMock()
    session.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return session


@pytest.fixture
def mock_session_factory(mock_session):
    factory = MagicMock(return_value=mock_session)
    return factory


@pytest.mark.asyncio
async def test_write_signal_calls_session_add(mock_session, mock_session_factory):
    """write_signal adds a FeedbackSignal row to the session."""
    # Mock the dedup query to return no existing signal
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("baloo.db.feedback_service.get_session_factory", return_value=mock_session_factory):
        with patch("baloo.db.feedback_service.get_settings") as mock_settings:
            mock_settings.return_value.database_url = "postgresql+asyncpg://localhost/test"
            mock_settings.return_value.database_enabled = True
            mock_settings.return_value.feedback_signals_enabled = True

            await FeedbackService.write_signal(
                repo="org/repo",
                pattern="except pass in retry loops is intentional",
                category="Silent Failures",
                developer="alice",
                file_glob="app/retry/*.py",
                thread_url="https://github.com/org/repo/pull/1#discussion_r123",
                pr_number=1,
            )

            mock_session.add.assert_called_once()
            added = mock_session.add.call_args[0][0]
            assert added.repo == "org/repo"
            assert added.pattern == "except pass in retry loops is intentional"
            assert added.category == "Silent Failures"
            assert added.developer == "alice"
            assert added.file_glob == "app/retry/*.py"


@pytest.mark.asyncio
async def test_write_signal_skipped_when_disabled(mock_session, mock_session_factory):
    """write_signal is a no-op when feedback signals are disabled."""
    with patch("baloo.db.feedback_service.get_settings") as mock_settings:
        mock_settings.return_value.feedback_signals_enabled = False

        await FeedbackService.write_signal(
            repo="org/repo",
            pattern="test",
            category="Bugs",
            developer="bob",
        )

        mock_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_write_signal_skipped_when_db_disabled(mock_session, mock_session_factory):
    """write_signal is a no-op when database is disabled."""
    with patch("baloo.db.feedback_service.get_settings") as mock_settings:
        mock_settings.return_value.feedback_signals_enabled = True
        mock_settings.return_value.database_enabled = False

        await FeedbackService.write_signal(
            repo="org/repo",
            pattern="test",
            category="Bugs",
            developer="bob",
        )

        mock_session.add.assert_not_called()


def test_format_signals_for_prompt_empty():
    """Empty signal list produces empty string."""
    assert FeedbackService.format_signals_for_prompt([]) == ""


def test_format_signals_for_prompt_formats_correctly():
    """Signals are formatted as a readable prompt section."""
    signals = [
        MagicMock(
            category="Silent Failures",
            file_glob="app/retry/*.py",
            pattern="except pass in retry loops is intentional",
            developer="alice",
            created_at=datetime(2026, 5, 7, tzinfo=timezone.utc),
        ),
        MagicMock(
            category="Security",
            file_glob=None,
            pattern="shell=True is acceptable in dev scripts",
            developer="bob",
            created_at=datetime(2026, 4, 20, tzinfo=timezone.utc),
        ),
    ]
    result = FeedbackService.format_signals_for_prompt(signals)
    assert "Silent Failures" in result
    assert "app/retry/*.py" in result
    assert "except pass in retry loops is intentional" in result
    assert "@alice" in result
    assert "Security" in result
    assert "shell=True" in result


@pytest.fixture
async def db_session_factory():
    """Set up an in-memory SQLite database and patch the session factory."""
    reset_engine()

    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)

    with patch("baloo.db.feedback_service.get_session_factory", return_value=factory):
        yield factory

    await engine.dispose()
    reset_engine()


@pytest.mark.asyncio
async def test_write_signal_sets_installation_id(db_session_factory):
    """Test that write_signal populates installation_id from settings."""
    with patch("baloo.db.feedback_service.get_settings") as mock_settings:
        mock_settings.return_value.database_url = "sqlite+aiosqlite://"
        mock_settings.return_value.database_enabled = True
        mock_settings.return_value.feedback_signals_enabled = True
        mock_settings.return_value.installation_id = "inst_abc"
        mock_settings.return_value.feedback_signals_ttl_days = 180

        await FeedbackService.write_signal(
            repo="owner/repo", pattern="test", category="Security", developer="alice"
        )

    async with db_session_factory() as session:
        result = await session.execute(select(FeedbackSignal))
        signals = result.scalars().all()
        assert len(signals) == 1
        assert signals[0].installation_id == "inst_abc"


@pytest.mark.asyncio
async def test_get_signals_filters_by_installation_id(db_session_factory):
    """Signals from a different tenant must not be returned."""
    async with db_session_factory() as session:
        async with session.begin():
            session.add(
                FeedbackSignal(
                    repo="owner/repo",
                    pattern="other tenant pattern",
                    category="Security",
                    developer="bob",
                    installation_id="other_tenant",
                    created_at=datetime.now(timezone.utc),
                )
            )

    with patch("baloo.db.feedback_service.get_settings") as mock_settings:
        mock_settings.return_value.database_url = "sqlite+aiosqlite://"
        mock_settings.return_value.database_enabled = True
        mock_settings.return_value.feedback_signals_enabled = True
        mock_settings.return_value.installation_id = "inst_abc"
        mock_settings.return_value.feedback_signals_ttl_days = 180

        signals = await FeedbackService.get_signals_for_repo("owner/repo")

    assert len(signals) == 0
