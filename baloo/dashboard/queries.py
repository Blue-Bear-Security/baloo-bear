"""Read-only database queries for the dashboard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from baloo.config.settings import get_settings
from baloo.db.engine import get_session_factory
from baloo.db.models import Finding, Review


class DashboardService:
    """Read-only queries powering dashboard pages."""

    @staticmethod
    async def get_overview_stats() -> dict:
        settings = get_settings()
        factory = get_session_factory(settings.database_url)

        async with factory() as session:
            now = datetime.now(timezone.utc)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

            total = (await session.execute(select(func.count(Review.id)))).scalar() or 0

            today = (
                await session.execute(
                    select(func.count(Review.id)).where(Review.started_at >= today_start)
                )
            ).scalar() or 0

            avg_duration = (
                await session.execute(
                    select(func.avg(Review.duration_seconds)).where(
                        Review.duration_seconds.is_not(None)
                    )
                )
            ).scalar()

            approved_count = (
                await session.execute(
                    select(func.count(Review.id)).where(Review.review_status == "approved")
                )
            ).scalar() or 0

            approval_rate = round(approved_count / total * 100, 1) if total else 0.0

            # Severity breakdown from findings
            severity_rows = (
                await session.execute(
                    select(Finding.severity, func.count(Finding.id)).group_by(Finding.severity)
                )
            ).all()
            severity = {row[0]: row[1] for row in severity_rows}

            recent = (
                await session.execute(
                    select(Review).order_by(Review.started_at.desc()).limit(5)
                )
            ).scalars().all()

        return {
            "total_reviews": total,
            "reviews_today": today,
            "avg_duration": round(avg_duration, 1) if avg_duration else 0,
            "approval_rate": approval_rate,
            "severity": severity,
            "recent_reviews": recent,
        }

    @staticmethod
    async def list_reviews(
        page: int = 1,
        per_page: int = 20,
        repo_filter: str | None = None,
        status_filter: str | None = None,
    ) -> dict:
        settings = get_settings()
        factory = get_session_factory(settings.database_url)

        async with factory() as session:
            q = select(Review)
            count_q = select(func.count(Review.id))

            if repo_filter:
                q = q.where(Review.repo_full_name == repo_filter)
                count_q = count_q.where(Review.repo_full_name == repo_filter)
            if status_filter:
                q = q.where(Review.review_status == status_filter)
                count_q = count_q.where(Review.review_status == status_filter)

            total = (await session.execute(count_q)).scalar() or 0

            q = q.order_by(Review.started_at.desc())
            q = q.offset((page - 1) * per_page).limit(per_page)

            reviews = (await session.execute(q)).scalars().all()

            # Distinct repos for filter dropdown
            repos = (
                await session.execute(
                    select(Review.repo_full_name).distinct().order_by(Review.repo_full_name)
                )
            ).scalars().all()

        total_pages = max(1, -(-total // per_page))  # ceil division
        return {
            "reviews": reviews,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
            "repos": repos,
        }

    @staticmethod
    async def get_review_detail(review_id: int) -> Review | None:
        settings = get_settings()
        factory = get_session_factory(settings.database_url)

        async with factory() as session:
            result = await session.execute(
                select(Review)
                .options(selectinload(Review.findings))
                .where(Review.id == review_id)
            )
            return result.scalars().first()

    @staticmethod
    async def get_analytics_data(days: int = 30) -> dict:
        settings = get_settings()
        factory = get_session_factory(settings.database_url)

        async with factory() as session:
            since = datetime.now(timezone.utc) - timedelta(days=days)

            # Reviews per day
            daily_rows = (
                await session.execute(
                    select(
                        func.date(Review.started_at).label("day"),
                        func.count(Review.id),
                    )
                    .where(Review.started_at >= since)
                    .group_by(func.date(Review.started_at))
                    .order_by(func.date(Review.started_at))
                )
            ).all()

            # Status distribution
            status_rows = (
                await session.execute(
                    select(Review.review_status, func.count(Review.id))
                    .where(Review.started_at >= since)
                    .group_by(Review.review_status)
                )
            ).all()

            # Severity distribution from findings
            severity_rows = (
                await session.execute(
                    select(Finding.severity, func.count(Finding.id))
                    .join(Review)
                    .where(Review.started_at >= since)
                    .group_by(Finding.severity)
                )
            ).all()

            # Top repos
            repo_rows = (
                await session.execute(
                    select(Review.repo_full_name, func.count(Review.id))
                    .where(Review.started_at >= since)
                    .group_by(Review.repo_full_name)
                    .order_by(func.count(Review.id).desc())
                    .limit(10)
                )
            ).all()

            # Total cost
            total_cost = (
                await session.execute(
                    select(func.sum(Review.cost_usd)).where(Review.started_at >= since)
                )
            ).scalar() or 0

        return {
            "daily": [{"day": str(r[0]), "count": r[1]} for r in daily_rows],
            "statuses": {r[0]: r[1] for r in status_rows},
            "severities": {r[0]: r[1] for r in severity_rows},
            "repos": [{"name": r[0], "count": r[1]} for r in repo_rows],
            "total_cost": round(total_cost, 2) if total_cost else 0,
        }
