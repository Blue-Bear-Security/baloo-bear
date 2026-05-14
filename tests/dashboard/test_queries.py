"""Cross-tenant isolation tests for DashboardService."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from baloo.db.engine import reset_engine
from baloo.db.models import Base, Review


@pytest.fixture
async def dashboard_db():
    reset_engine()
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    with patch("baloo.dashboard.queries.get_session_factory", return_value=factory):
        yield factory
    await engine.dispose()
    reset_engine()


@pytest.mark.asyncio
async def test_get_overview_stats_only_counts_own_tenant(dashboard_db):
    """overview stats must not count reviews from other tenants."""
    async with dashboard_db() as session:
        async with session.begin():
            session.add(
                Review(
                    repo_full_name="owner/repo",
                    pr_number=1,
                    review_status="approved",
                    trigger_reason="test",
                    started_at=datetime.now(timezone.utc),
                    installation_id="tenant_a",
                )
            )
            session.add(
                Review(
                    repo_full_name="owner/repo",
                    pr_number=2,
                    review_status="approved",
                    trigger_reason="test",
                    started_at=datetime.now(timezone.utc),
                    installation_id="tenant_b",
                )
            )

    with patch("baloo.dashboard.queries.get_settings") as mock_settings:
        mock_settings.return_value.database_url = "sqlite+aiosqlite://"
        mock_settings.return_value.installation_id = "tenant_a"

        from baloo.dashboard.queries import DashboardService

        stats = await DashboardService.get_overview_stats()

    assert stats["total_reviews"] == 1


@pytest.mark.asyncio
async def test_list_reviews_only_returns_own_tenant(dashboard_db):
    """list_reviews must not return reviews from other tenants."""
    async with dashboard_db() as session:
        async with session.begin():
            for i, inst in enumerate(["tenant_a", "tenant_b", "tenant_a"]):
                session.add(
                    Review(
                        repo_full_name="owner/repo",
                        pr_number=i + 1,
                        review_status="approved",
                        trigger_reason="test",
                        started_at=datetime.now(timezone.utc),
                        installation_id=inst,
                    )
                )

    with patch("baloo.dashboard.queries.get_settings") as mock_settings:
        mock_settings.return_value.database_url = "sqlite+aiosqlite://"
        mock_settings.return_value.installation_id = "tenant_a"

        from baloo.dashboard.queries import DashboardService

        result = await DashboardService.list_reviews()

    assert result["total"] == 2
    assert all(r.installation_id == "tenant_a" for r in result["reviews"])
