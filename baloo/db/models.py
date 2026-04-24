"""SQLAlchemy ORM models for review persistence."""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repo_full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    pr_number: Mapped[int] = mapped_column(Integer, nullable=False)
    pr_title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    pr_author: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    review_status: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # approved, changes_requested, commented, error
    trigger_reason: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tokens_input: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_output: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    agent_turns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    files_examined: Mapped[int | None] = mapped_column(Integer, nullable=True)
    auto_approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    fidelity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    fallback_model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    findings: Mapped[list["Finding"]] = relationship(
        "Finding", back_populates="review", cascade="all, delete-orphan"
    )
    logs: Mapped[list["ReviewLog"]] = relationship(
        "ReviewLog", back_populates="review", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_reviews_repo_pr", "repo_full_name", "pr_number"),
        Index("ix_reviews_started_at", "started_at"),
        Index("ix_reviews_error_category", "error_category"),
    )


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    line_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="Quality")
    body: Mapped[str] = mapped_column(Text, nullable=False)

    review: Mapped["Review"] = relationship("Review", back_populates="findings")

    __table_args__ = (Index("ix_findings_review_id", "review_id"),)


class ReviewLog(Base):
    __tablename__ = "review_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    review: Mapped["Review"] = relationship("Review", back_populates="logs")

    __table_args__ = (
        Index("ix_review_logs_review_created", "review_id", "created_at"),
        Index("ix_review_logs_created_at", "created_at"),
    )
