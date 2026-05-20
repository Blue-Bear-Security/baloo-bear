"""ReviewService for persisting review data to the database."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from baloo.config.settings import get_settings
from baloo.db.engine import get_session_factory
from baloo.db.models import Finding, Review

logger = logging.getLogger(__name__)


class ReviewServiceError(Exception):
    """Base exception for ReviewService."""

    pass


class ReviewNotFoundError(ReviewServiceError):
    """Raised when a review is not found in the database."""

    pass


class DuplicateReviewError(ReviewServiceError):
    """Raised when a review is already in progress for the given PR."""

    pass


class ReviewCompleteDTO(BaseModel):
    """Data transfer object for completing a review."""

    pr_title: str = ""
    pr_author: str = ""
    commit_sha: str = ""
    review_status: str = "commented"
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    model_used: str | None = None
    tokens_input: int | None = None
    tokens_output: int | None = None
    cost_usd: float | None = None
    agent_turns: int | None = None
    files_examined: int | None = None
    auto_approved: bool | None = None
    fidelity_score: float | None = None
    error_message: str | None = None
    error_category: str | None = None
    fallback_model: str | None = None
    findings: list[dict[str, Any]] = Field(default_factory=list)


class ReviewService:
    """Service for persisting review and finding records."""

    @staticmethod
    async def start_review(
        repo_full_name: str,
        pr_number: int,
        trigger_reason: str,
        started_at: datetime,
        commit_sha: str = "",
    ) -> int:
        """
        Create an in-progress review row at the start of a review.

        Returns:
            The review ID.

        Raises:
            ReviewServiceError: If database operation fails.
        """
        try:
            settings = get_settings()
            session_factory = get_session_factory(settings.database_url)
            stale_cutoff = started_at - timedelta(minutes=settings.review_stale_timeout_minutes)

            async with session_factory() as session:
                async with session.begin():
                    # Cancel in-progress reviews for the same PR on a different SHA —
                    # a new commit has arrived and the old review is now obsolete.
                    await session.execute(
                        update(Review)
                        .where(
                            Review.repo_full_name == repo_full_name,
                            Review.pr_number == pr_number,
                            Review.commit_sha != commit_sha,
                            Review.review_status == "in_progress",
                        )
                        .values(
                            review_status="cancelled",
                            error_message="superseded by new commit",
                        )
                    )

                    # Mark stale in-progress reviews for the same SHA as error so the
                    # unique partial index won't block a retry.
                    await session.execute(
                        update(Review)
                        .where(
                            Review.repo_full_name == repo_full_name,
                            Review.pr_number == pr_number,
                            Review.commit_sha == commit_sha,
                            Review.review_status == "in_progress",
                            Review.started_at < stale_cutoff,
                        )
                        .values(
                            review_status="error",
                            error_message="stale: review abandoned mid-flight",
                            error_category="stale",
                        )
                    )

                    review = Review(
                        repo_full_name=repo_full_name,
                        pr_number=pr_number,
                        commit_sha=commit_sha,
                        review_status="in_progress",
                        trigger_reason=trigger_reason,
                        started_at=started_at,
                        installation_id=settings.installation_id,
                    )
                    session.add(review)
                    try:
                        await session.flush()
                    except IntegrityError as exc:
                        raise DuplicateReviewError(
                            f"Review already in progress for {repo_full_name}#{pr_number}"
                        ) from exc

                logger.info(f"Started review {review.id} for {repo_full_name}#{pr_number}")
                return review.id

        except DuplicateReviewError:
            raise
        except Exception as e:
            logger.error(f"Failed to start review for {repo_full_name}#{pr_number}: {e}")
            raise ReviewServiceError(f"Failed to start review: {e}") from e

    @staticmethod
    async def complete_review(
        review_id: int,
        data: ReviewCompleteDTO,
    ) -> None:
        """
        Update an existing review row with completion data and findings.

        Args:
            review_id: ID of the review to complete.
            data: DTO containing review results.

        Raises:
            ReviewNotFoundError: If review_id does not exist.
            ReviewServiceError: If database operation fails.
        """
        try:
            settings = get_settings()
            session_factory = get_session_factory(settings.database_url)

            async with session_factory() as session:
                async with session.begin():
                    review = await session.get(Review, review_id)
                    if not review:
                        raise ReviewNotFoundError(f"Review {review_id} not found")

                    review.pr_title = data.pr_title
                    review.pr_author = data.pr_author
                    review.commit_sha = data.commit_sha
                    review.review_status = data.review_status
                    review.completed_at = data.completed_at
                    review.duration_seconds = data.duration_seconds
                    review.model_used = data.model_used
                    review.tokens_input = data.tokens_input
                    review.tokens_output = data.tokens_output
                    review.cost_usd = data.cost_usd
                    review.agent_turns = data.agent_turns
                    review.files_examined = data.files_examined
                    review.auto_approved = data.auto_approved
                    review.fidelity_score = data.fidelity_score
                    review.error_message = data.error_message
                    review.error_category = data.error_category
                    review.fallback_model = data.fallback_model

                    if data.findings:
                        for f in data.findings:
                            finding = Finding(
                                review_id=review.id,
                                file_path=f.get("file_path", ""),
                                line_number=f.get("line_number"),
                                severity=f.get("severity", "MEDIUM"),
                                category=f.get("category", "Quality"),
                                body=f.get("body", ""),
                                installation_id=settings.installation_id,
                            )
                            session.add(finding)

                logger.info(
                    f"Completed review {review_id} "
                    f"({data.review_status}, {len(data.findings)} findings)"
                )

        except ReviewNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to complete review {review_id}: {e}")
            raise ReviewServiceError(f"Failed to complete review: {e}") from e

    @staticmethod
    async def is_review_cancelled(review_id: int) -> bool:
        """Return True if the review row has been marked cancelled (by another replica)."""
        try:
            settings = get_settings()
            session_factory = get_session_factory(settings.database_url)
            async with session_factory() as session:
                review = await session.get(Review, review_id)
                return review is not None and review.review_status == "cancelled"
        except Exception as e:
            logger.warning(f"Failed to check cancellation status for review {review_id}: {e}")
            return False
