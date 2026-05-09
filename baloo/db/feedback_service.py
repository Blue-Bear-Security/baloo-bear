"""CRUD service for feedback signals."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from baloo.config.settings import get_settings
from baloo.db.engine import get_session_factory
from baloo.db.models import FeedbackSignal

logger = logging.getLogger(__name__)


class FeedbackService:
    """Service for reading and writing per-repo feedback signals."""

    @staticmethod
    async def write_signal(
        *,
        repo: str,
        pattern: str,
        category: str,
        developer: str,
        file_glob: str | None = None,
        thread_url: str | None = None,
        pr_number: int | None = None,
    ) -> None:
        """Write a feedback signal to the database.

        No-op if feedback signals or the database are disabled.
        """
        settings = get_settings()
        if not settings.feedback_signals_enabled or not settings.database_enabled:
            return

        session_factory = get_session_factory(settings.database_url)
        async with session_factory() as session:
            async with session.begin():
                signal = FeedbackSignal(
                    repo=repo,
                    pattern=pattern,
                    category=category,
                    file_glob=file_glob,
                    developer=developer,
                    thread_url=thread_url,
                    pr_number=pr_number,
                    created_at=datetime.now(timezone.utc),
                )
                session.add(signal)

        logger.info(
            "Wrote feedback signal for %s: [%s] %s (by @%s)",
            repo,
            category,
            pattern[:80],
            developer,
        )

    @staticmethod
    async def get_signals_for_repo(repo: str) -> list[FeedbackSignal]:
        """Fetch active (non-expired) feedback signals for a repo.

        Returns an empty list if feedback signals or the database are disabled.
        """
        settings = get_settings()
        if not settings.feedback_signals_enabled or not settings.database_enabled:
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.feedback_signals_ttl_days)

        session_factory = get_session_factory(settings.database_url)
        async with session_factory() as session:
            from sqlalchemy import select

            stmt = (
                select(FeedbackSignal)
                .where(FeedbackSignal.repo == repo)
                .where(FeedbackSignal.created_at > cutoff)
                .order_by(FeedbackSignal.created_at.desc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    @staticmethod
    def format_signals_for_prompt(signals: list) -> str:
        """Format feedback signals as a prompt section for the review agent.

        Args:
            signals: List of FeedbackSignal objects.

        Returns:
            Formatted string to inject into the review prompt, or empty string.
        """
        if not signals:
            return ""

        lines = []
        for signal in signals:
            scope = f" in `{signal.file_glob}`" if signal.file_glob else ""
            date_str = signal.created_at.strftime("%Y-%m-%d")
            lines.append(
                f"- {signal.category}{scope}: "
                f'"{signal.pattern}" '
                f"(@{signal.developer}, {date_str})"
            )

        return "\n".join(lines)
