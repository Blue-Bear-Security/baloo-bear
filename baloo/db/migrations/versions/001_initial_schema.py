"""Initial schema: reviews and findings tables

Revision ID: 001
Revises:
Create Date: 2026-02-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("repo_full_name", sa.String(255), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=False),
        sa.Column("pr_title", sa.String(500), nullable=False, server_default=""),
        sa.Column("pr_author", sa.String(255), nullable=False, server_default=""),
        sa.Column("commit_sha", sa.String(40), nullable=False, server_default=""),
        sa.Column("review_status", sa.String(50), nullable=False),
        sa.Column("trigger_reason", sa.String(100), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("model_used", sa.String(100), nullable=True),
        sa.Column("tokens_input", sa.Integer(), nullable=True),
        sa.Column("tokens_output", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("agent_turns", sa.Integer(), nullable=True),
        sa.Column("files_examined", sa.Integer(), nullable=True),
        sa.Column("auto_approved", sa.Boolean(), nullable=True),
        sa.Column("fidelity_score", sa.Float(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reviews_repo_pr", "reviews", ["repo_full_name", "pr_number"])
    op.create_index("ix_reviews_started_at", "reviews", ["started_at"])

    op.create_table(
        "findings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "review_id",
            sa.Integer(),
            sa.ForeignKey("reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=True),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("category", sa.String(50), nullable=False, server_default="Quality"),
        sa.Column("body", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_findings_review_id", "findings", ["review_id"])


def downgrade() -> None:
    op.drop_table("findings")
    op.drop_table("reviews")
