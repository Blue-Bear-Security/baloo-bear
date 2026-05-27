"""Read-only database queries for the dashboard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from baloo.config.settings import get_settings
from baloo.db.engine import get_session_factory
from baloo.db.models import Finding, FindingOutcome, Review, ReviewLog
from baloo.db.tenant import apply_tenant_filter


class DashboardService:
    """Read-only queries powering dashboard pages."""

    @staticmethod
    async def get_overview_stats() -> dict:
        settings = get_settings()
        factory = get_session_factory(settings.database_url)
        installation_id = settings.installation_id

        async with factory() as session:
            now = datetime.now(timezone.utc)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

            total_stmt = apply_tenant_filter(select(func.count(Review.id)), Review, installation_id)
            total = (await session.execute(total_stmt)).scalar() or 0

            today_stmt = apply_tenant_filter(
                select(func.count(Review.id)).where(Review.started_at >= today_start),
                Review,
                installation_id,
            )
            today = (await session.execute(today_stmt)).scalar() or 0

            avg_dur_stmt = apply_tenant_filter(
                select(func.avg(Review.duration_seconds)).where(
                    Review.duration_seconds.is_not(None)
                ),
                Review,
                installation_id,
            )
            avg_duration = (await session.execute(avg_dur_stmt)).scalar()

            approved_stmt = apply_tenant_filter(
                select(func.count(Review.id)).where(Review.review_status == "approved"),
                Review,
                installation_id,
            )
            approved_count = (await session.execute(approved_stmt)).scalar() or 0

            approval_rate = round(approved_count / total * 100, 1) if total else 0.0

            # Severity breakdown from findings
            severity_stmt = apply_tenant_filter(
                select(Finding.severity, func.count(Finding.id)).group_by(Finding.severity),
                Finding,
                installation_id,
            )
            severity_rows = (await session.execute(severity_stmt)).all()
            severity = {row[0]: row[1] for row in severity_rows}

            # Error / agent_error counts
            error_statuses = ["error", "agent_error"]
            errors_total_stmt = apply_tenant_filter(
                select(func.count(Review.id)).where(Review.review_status.in_(error_statuses)),
                Review,
                installation_id,
            )
            errors_total = (await session.execute(errors_total_stmt)).scalar() or 0

            errors_today_stmt = apply_tenant_filter(
                select(func.count(Review.id)).where(
                    Review.review_status.in_(error_statuses),
                    Review.started_at >= today_start,
                ),
                Review,
                installation_id,
            )
            errors_today = (await session.execute(errors_today_stmt)).scalar() or 0

            error_rate = round(errors_total / total * 100, 1) if total else 0.0

            # Error category breakdown
            error_cat_stmt = apply_tenant_filter(
                select(Review.error_category, func.count(Review.id))
                .where(Review.error_category.is_not(None))
                .group_by(Review.error_category)
                .order_by(func.count(Review.id).desc()),
                Review,
                installation_id,
            )
            error_category_rows = (await session.execute(error_cat_stmt)).all()
            error_categories = {row[0]: row[1] for row in error_category_rows}

            # Recent failures
            recent_failures_stmt = apply_tenant_filter(
                select(Review)
                .where(Review.review_status.in_(error_statuses))
                .order_by(Review.started_at.desc())
                .limit(5),
                Review,
                installation_id,
            )
            recent_failures = (await session.execute(recent_failures_stmt)).scalars().all()

            # Recent reviews
            recent_stmt = apply_tenant_filter(
                select(Review).order_by(Review.started_at.desc()).limit(5),
                Review,
                installation_id,
            )
            recent = (await session.execute(recent_stmt)).scalars().all()

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

            hourly_stmt = apply_tenant_filter(
                select(
                    hour_label.label("hour"),
                    func.count(Review.id),
                )
                .where(Review.started_at >= last_24h)
                .group_by("hour")
                .order_by("hour"),
                Review,
                installation_id,
            )
            hourly_rows = (await session.execute(hourly_stmt)).all()

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
        installation_id = settings.installation_id

        async with factory() as session:
            q = select(Review)
            count_q = select(func.count(Review.id))

            q = apply_tenant_filter(q, Review, installation_id)
            count_q = apply_tenant_filter(count_q, Review, installation_id)

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
            repos_stmt = apply_tenant_filter(
                select(Review.repo_full_name).distinct().order_by(Review.repo_full_name),
                Review,
                installation_id,
            )
            repos = (await session.execute(repos_stmt)).scalars().all()

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
        installation_id = settings.installation_id

        async with factory() as session:
            stmt = apply_tenant_filter(
                select(Review).options(selectinload(Review.findings)).where(Review.id == review_id),
                Review,
                installation_id,
            )
            result = await session.execute(stmt)
            return result.scalars().first()

    @staticmethod
    async def get_review_logs(review_id: int) -> list[ReviewLog]:
        settings = get_settings()
        factory = get_session_factory(settings.database_url)
        installation_id = settings.installation_id

        async with factory() as session:
            stmt = apply_tenant_filter(
                select(ReviewLog)
                .where(ReviewLog.review_id == review_id)
                .order_by(ReviewLog.created_at.asc()),
                ReviewLog,
                installation_id,
            )
            result = await session.execute(stmt)
            return result.scalars().all()

    @staticmethod
    async def get_analytics_data(days: int = 30) -> dict:
        settings = get_settings()
        factory = get_session_factory(settings.database_url)
        installation_id = settings.installation_id

        async with factory() as session:
            now = datetime.now(timezone.utc)
            since = now - timedelta(days=days)
            prev_since = now - timedelta(days=2 * days)

            # Reviews per day
            daily_rows = (
                await session.execute(
                    apply_tenant_filter(
                        select(
                            func.date(Review.started_at).label("day"),
                            func.count(Review.id),
                        )
                        .where(Review.started_at >= since)
                        .group_by(func.date(Review.started_at))
                        .order_by(func.date(Review.started_at)),
                        Review,
                        installation_id,
                    )
                )
            ).all()

            # Current period stats
            error_statuses = ["error", "agent_error"]
            total_cost = (
                await session.execute(
                    apply_tenant_filter(
                        select(func.sum(Review.cost_usd)).where(Review.started_at >= since),
                        Review,
                        installation_id,
                    )
                )
            ).scalar() or 0
            error_total = (
                await session.execute(
                    apply_tenant_filter(
                        select(func.count(Review.id)).where(
                            Review.started_at >= since,
                            Review.review_status.in_(error_statuses),
                        ),
                        Review,
                        installation_id,
                    )
                )
            ).scalar() or 0
            total_in_period = (
                await session.execute(
                    apply_tenant_filter(
                        select(func.count(Review.id)).where(Review.started_at >= since),
                        Review,
                        installation_id,
                    )
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
                    apply_tenant_filter(
                        select(func.sum(Review.cost_usd)).where(
                            Review.started_at >= prev_since, Review.started_at < since
                        ),
                        Review,
                        installation_id,
                    )
                )
            ).scalar() or 0
            prev_error_total = (
                await session.execute(
                    apply_tenant_filter(
                        select(func.count(Review.id)).where(
                            Review.started_at >= prev_since,
                            Review.started_at < since,
                            Review.review_status.in_(error_statuses),
                        ),
                        Review,
                        installation_id,
                    )
                )
            ).scalar() or 0
            prev_total_in_period = (
                await session.execute(
                    apply_tenant_filter(
                        select(func.count(Review.id)).where(
                            Review.started_at >= prev_since, Review.started_at < since
                        ),
                        Review,
                        installation_id,
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
                    apply_tenant_filter(
                        select(Review.review_status, func.count(Review.id))
                        .where(Review.started_at >= since)
                        .group_by(Review.review_status),
                        Review,
                        installation_id,
                    )
                )
            ).all()

            # Severity distribution from findings (current period)
            severity_rows = (
                await session.execute(
                    apply_tenant_filter(
                        select(Finding.severity, func.count(Finding.id))
                        .join(Review)
                        .where(Review.started_at >= since)
                        .group_by(Finding.severity),
                        Review,
                        installation_id,
                    )
                )
            ).all()

            # Top repos (current period)
            repo_rows = (
                await session.execute(
                    apply_tenant_filter(
                        select(Review.repo_full_name, func.count(Review.id))
                        .where(Review.started_at >= since)
                        .group_by(Review.repo_full_name)
                        .order_by(func.count(Review.id).desc())
                        .limit(10),
                        Review,
                        installation_id,
                    )
                )
            ).all()

            # Error category breakdown for the period
            error_category_rows = (
                await session.execute(
                    apply_tenant_filter(
                        select(Review.error_category, func.count(Review.id))
                        .where(
                            Review.started_at >= since,
                            Review.error_category.is_not(None),
                        )
                        .group_by(Review.error_category)
                        .order_by(func.count(Review.id).desc()),
                        Review,
                        installation_id,
                    )
                )
            ).all()

            # Daily error counts
            daily_error_rows = (
                await session.execute(
                    apply_tenant_filter(
                        select(
                            func.date(Review.started_at).label("day"),
                            func.count(Review.id),
                        )
                        .where(
                            Review.started_at >= since,
                            Review.review_status.in_(error_statuses),
                        )
                        .group_by(func.date(Review.started_at))
                        .order_by(func.date(Review.started_at)),
                        Review,
                        installation_id,
                    )
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

    @staticmethod
    async def get_outcomes_data(days: int = 90, repo_filter: str | None = None) -> dict:
        settings = get_settings()
        factory = get_session_factory(settings.database_url)
        installation_id = settings.installation_id

        async with factory() as session:
            now = datetime.now(timezone.utc)
            since = now - timedelta(days=days)

            def _base_filters():
                filters = [FindingOutcome.labeled_at >= since]
                if repo_filter:
                    filters.append(FindingOutcome.repo_full_name == repo_filter)
                if installation_id:
                    filters.append(FindingOutcome.installation_id == installation_id)
                return filters

            # --- Totals and rates ---
            total = (
                await session.execute(select(func.count(FindingOutcome.id)).where(*_base_filters()))
            ).scalar() or 0

            outcome_rows = (
                await session.execute(
                    select(FindingOutcome.outcome, func.count(FindingOutcome.id))
                    .where(*_base_filters())
                    .group_by(FindingOutcome.outcome)
                )
            ).all()
            outcomes = {r[0]: r[1] for r in outcome_rows}

            actioned = outcomes.get("actioned", 0)
            acknowledged = outcomes.get("acknowledged", 0)
            disputed = outcomes.get("disputed", 0)
            ignored = outcomes.get("ignored", 0)

            hit_rate = round((actioned + acknowledged) / total * 100, 1) if total else 0.0
            noise_rate = round((disputed + ignored) / total * 100, 1) if total else 0.0

            # --- By severity ---
            severity_rows = (
                await session.execute(
                    select(
                        Finding.severity,
                        FindingOutcome.outcome,
                        func.count(FindingOutcome.id),
                    )
                    .join(Finding, FindingOutcome.finding_id == Finding.id)
                    .where(*_base_filters())
                    .group_by(Finding.severity, FindingOutcome.outcome)
                )
            ).all()

            sev_map: dict[str, dict] = {}
            for sev, outcome, cnt in severity_rows:
                if sev not in sev_map:
                    sev_map[sev] = {"total": 0, "actioned": 0}
                sev_map[sev]["total"] += cnt
                if outcome == "actioned":
                    sev_map[sev]["actioned"] += cnt
            severity_data = {
                sev: {
                    "total": v["total"],
                    "actioned": v["actioned"],
                    "hit_rate": round(v["actioned"] / v["total"] * 100, 1) if v["total"] else 0.0,
                }
                for sev, v in sev_map.items()
            }

            # --- By category ---
            category_rows = (
                await session.execute(
                    select(
                        Finding.category,
                        FindingOutcome.outcome,
                        func.count(FindingOutcome.id),
                    )
                    .join(Finding, FindingOutcome.finding_id == Finding.id)
                    .where(*_base_filters())
                    .group_by(Finding.category, FindingOutcome.outcome)
                )
            ).all()

            cat_map: dict[str, dict] = {}
            for cat, outcome, cnt in category_rows:
                if cat not in cat_map:
                    cat_map[cat] = {"total": 0, "actioned": 0}
                cat_map[cat]["total"] += cnt
                if outcome == "actioned":
                    cat_map[cat]["actioned"] += cnt
            category_data = {
                cat: {
                    "total": v["total"],
                    "actioned": v["actioned"],
                    "hit_rate": round(v["actioned"] / v["total"] * 100, 1) if v["total"] else 0.0,
                }
                for cat, v in cat_map.items()
            }

            # --- Daily accuracy trends ---
            daily_rows = (
                await session.execute(
                    select(
                        func.date(FindingOutcome.labeled_at).label("day"),
                        FindingOutcome.outcome,
                        func.count(FindingOutcome.id),
                    )
                    .where(*_base_filters())
                    .group_by("day", FindingOutcome.outcome)
                    .order_by("day")
                )
            ).all()

            day_map: dict[str, dict] = {}
            for day, outcome, cnt in daily_rows:
                day_key = str(day)
                if day_key not in day_map:
                    day_map[day_key] = {
                        "total": 0,
                        "actioned": 0,
                        "acknowledged": 0,
                        "disputed": 0,
                        "ignored": 0,
                    }
                day_map[day_key]["total"] += cnt
                if outcome in day_map[day_key]:
                    day_map[day_key][outcome] += cnt
            trends = [
                {
                    "day": d,
                    "total": v["total"],
                    "hit_rate": round(v["actioned"] / v["total"] * 100, 1) if v["total"] else 0.0,
                    "noise_rate": (
                        round((v["disputed"] + v["ignored"]) / v["total"] * 100, 1)
                        if v["total"]
                        else 0.0
                    ),
                }
                for d, v in day_map.items()
            ]

            # --- Repos for filter dropdown ---
            repos_stmt = apply_tenant_filter(
                select(FindingOutcome.repo_full_name)
                .distinct()
                .order_by(FindingOutcome.repo_full_name),
                FindingOutcome,
                installation_id,
            )
            repos = (await session.execute(repos_stmt)).scalars().all()

        return {
            "total": total,
            "outcomes": outcomes,
            "hit_rate": hit_rate,
            "noise_rate": noise_rate,
            "severity_data": severity_data,
            "category_data": category_data,
            "trends": trends,
            "repos": repos,
        }
