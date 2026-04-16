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

            # Error / agent_error counts
            error_statuses = ["error", "agent_error"]
            errors_total = (
                await session.execute(
                    select(func.count(Review.id)).where(Review.review_status.in_(error_statuses))
                )
            ).scalar() or 0

            errors_today = (
                await session.execute(
                    select(func.count(Review.id)).where(
                        Review.review_status.in_(error_statuses),
                        Review.started_at >= today_start,
                    )
                )
            ).scalar() or 0

            error_rate = round(errors_total / total * 100, 1) if total else 0.0

            # Error category breakdown
            error_category_rows = (
                await session.execute(
                    select(Review.error_category, func.count(Review.id))
                    .where(Review.error_category.is_not(None))
                    .group_by(Review.error_category)
                    .order_by(func.count(Review.id).desc())
                )
            ).all()
            error_categories = {row[0]: row[1] for row in error_category_rows}

            # Recent failures
            recent_failures = (
                (
                    await session.execute(
                        select(Review)
                        .where(Review.review_status.in_(error_statuses))
                        .order_by(Review.started_at.desc())
                        .limit(5)
                    )
                )
                .scalars()
                .all()
            )

            # Recent reviews
            recent = (
                (await session.execute(select(Review).order_by(Review.started_at.desc()).limit(5)))
                .scalars()
                .all()
            )

            # Reviews per hour (last 24h)
            last_24h = now - timedelta(hours=24)

            # Dialect-aware hour grouping
            if "postgres" in settings.database_url:
                hour_label = func.to_char(
                    func.date_trunc("hour", Review.started_at), "YYYY-MM-DD HH24:00"
                )
            else:
                # Default to SQLite
                hour_label = func.strftime("%Y-%m-%d %H:00", Review.started_at)

            hourly_rows = (
                await session.execute(
                    select(
                        hour_label.label("hour"),
                        func.count(Review.id),
                    )
                    .where(Review.started_at >= last_24h)
                    .group_by("hour")
                    .order_by("hour")
                )
            ).all()

        return {
            "total_reviews": total,
            "reviews_today": today,
            "avg_duration": round(avg_duration, 1) if avg_duration else 0,
            "approval_rate": approval_rate,
            "severity": severity,
            "recent_reviews": recent,
            "errors_total": errors_total,
            "errors_today": errors_today,
            "error_rate": error_rate,
            "error_categories": error_categories,
            "recent_failures": recent_failures,
            "hourly_activity": [{"hour": r[0], "count": r[1]} for r in hourly_rows],
        }

    @staticmethod
    async def list_reviews(
        page: int = 1,
        per_page: int = 20,
        repo_filter: str | None = None,
        status_filter: str | None = None,
        search_filter: str | None = None,
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
            if search_filter:
                search_val = f"%{search_filter}%"
                q = q.where(
                    (Review.pr_title.like(search_val)) | (Review.pr_author.like(search_val))
                )
                count_q = count_q.where(
                    (Review.pr_title.like(search_val)) | (Review.pr_author.like(search_val))
                )

            total = (await session.execute(count_q)).scalar() or 0

            q = q.order_by(Review.started_at.desc())
            q = q.offset((page - 1) * per_page).limit(per_page)

            reviews = (await session.execute(q)).scalars().all()

            # Distinct repos for filter dropdown
            repos = (
                (
                    await session.execute(
                        select(Review.repo_full_name).distinct().order_by(Review.repo_full_name)
                    )
                )
                .scalars()
                .all()
            )

        total_pages = max(1, -(-total // per_page))  # ceil division
        return {
            "reviews": reviews,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
            "repos": repos,
            "search": search_filter,
        }

    @staticmethod
    async def get_review_detail(review_id: int) -> Review | None:
        settings = get_settings()
        factory = get_session_factory(settings.database_url)

        async with factory() as session:
            result = await session.execute(
                select(Review).options(selectinload(Review.findings)).where(Review.id == review_id)
            )
            return result.scalars().first()

    @staticmethod
    async def get_analytics_data(days: int = 30) -> dict:
        settings = get_settings()
        factory = get_session_factory(settings.database_url)

        async with factory() as session:
            now = datetime.now(timezone.utc)
            since = now - timedelta(days=days)
            prev_since = now - timedelta(days=2 * days)

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

            # Current period stats
            total_cost = (
                await session.execute(
                    select(func.sum(Review.cost_usd)).where(Review.started_at >= since)
                )
            ).scalar() or 0
            error_statuses = ["error", "agent_error"]
            error_total = (
                await session.execute(
                    select(func.count(Review.id)).where(
                        Review.started_at >= since,
                        Review.review_status.in_(error_statuses),
                    )
                )
            ).scalar() or 0
            total_in_period = (
                await session.execute(
                    select(func.count(Review.id)).where(Review.started_at >= since)
                )
            ).scalar() or 0
            success_rate = (
                round((total_in_period - error_total) / total_in_period * 100, 1)
                if total_in_period
                else 100.0
            )

            # Previous period stats for trends
            prev_total_cost = (
                await session.execute(
                    select(func.sum(Review.cost_usd)).where(
                        Review.started_at >= prev_since, Review.started_at < since
                    )
                )
            ).scalar() or 0
            prev_error_total = (
                await session.execute(
                    select(func.count(Review.id)).where(
                        Review.started_at >= prev_since,
                        Review.started_at < since,
                        Review.review_status.in_(error_statuses),
                    )
                )
            ).scalar() or 0
            prev_total_in_period = (
                await session.execute(
                    select(func.count(Review.id)).where(
                        Review.started_at >= prev_since, Review.started_at < since
                    )
                )
            ).scalar() or 0
            prev_success_rate = (
                round((prev_total_in_period - prev_error_total) / prev_total_in_period * 100, 1)
                if prev_total_in_period
                else 100.0
            )

            # Status distribution (current period)
            status_rows = (
                await session.execute(
                    select(Review.review_status, func.count(Review.id))
                    .where(Review.started_at >= since)
                    .group_by(Review.review_status)
                )
            ).all()

            # Severity distribution from findings (current period)
            severity_rows = (
                await session.execute(
                    select(Finding.severity, func.count(Finding.id))
                    .join(Review)
                    .where(Review.started_at >= since)
                    .group_by(Finding.severity)
                )
            ).all()

            # Top repos (current period)
            repo_rows = (
                await session.execute(
                    select(Review.repo_full_name, func.count(Review.id))
                    .where(Review.started_at >= since)
                    .group_by(Review.repo_full_name)
                    .order_by(func.count(Review.id).desc())
                    .limit(10)
                )
            ).all()

            # Error category breakdown for the period
            error_category_rows = (
                await session.execute(
                    select(Review.error_category, func.count(Review.id))
                    .where(
                        Review.started_at >= since,
                        Review.error_category.is_not(None),
                    )
                    .group_by(Review.error_category)
                    .order_by(func.count(Review.id).desc())
                )
            ).all()

            # Daily error counts
            daily_error_rows = (
                await session.execute(
                    select(
                        func.date(Review.started_at).label("day"),
                        func.count(Review.id),
                    )
                    .where(
                        Review.started_at >= since,
                        Review.review_status.in_(error_statuses),
                    )
                    .group_by(func.date(Review.started_at))
                    .order_by(func.date(Review.started_at))
                )
            ).all()

        return {
            "daily": [{"day": str(r[0]), "count": r[1]} for r in daily_rows],
            "statuses": {r[0]: r[1] for r in status_rows},
            "severities": {r[0]: r[1] for r in severity_rows},
            "repos": [{"name": r[0], "count": r[1]} for r in repo_rows],
            "total_cost": round(total_cost, 2) if total_cost else 0,
            "prev_total_cost": round(prev_total_cost, 2) if prev_total_cost else 0,
            "error_categories": {r[0]: r[1] for r in error_category_rows},
            "daily_errors": [{"day": str(r[0]), "count": r[1]} for r in daily_error_rows],
            "success_rate": success_rate,
            "prev_success_rate": prev_success_rate,
            "error_total": error_total,
            "prev_error_total": prev_error_total,
            "total_in_period": total_in_period,
            "prev_total_in_period": prev_total_in_period,
        }
