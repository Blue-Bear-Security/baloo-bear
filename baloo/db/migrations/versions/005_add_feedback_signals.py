"""Add feedback_signals table for thread agent memory.

Revision ID: 005
Revises: 004
Create Date: 2026-05-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: str = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "feedback_signals" not in existing_tables:
        op.create_table(
            "feedback_signals",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("repo", sa.Text, nullable=False),
            sa.Column("pattern", sa.Text, nullable=False),
            sa.Column("category", sa.String(50), nullable=False),
            sa.Column("file_glob", sa.Text, nullable=True),
            sa.Column("developer", sa.String(255), nullable=False),
            sa.Column("thread_url", sa.Text, nullable=True),
            sa.Column("pr_number", sa.Integer, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_matched_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("times_matched", sa.Integer, nullable=False, server_default="0"),
        )
        op.create_index("ix_feedback_signals_repo", "feedback_signals", ["repo"])
        op.create_index(
            "uq_feedback_signals_repo_cat_pattern",
            "feedback_signals",
            ["repo", "category", "pattern"],
            unique=True,
        )


def downgrade() -> None:
    op.drop_index("uq_feedback_signals_repo_cat_pattern", table_name="feedback_signals")
    op.drop_index("ix_feedback_signals_repo", table_name="feedback_signals")
    op.drop_table("feedback_signals")
