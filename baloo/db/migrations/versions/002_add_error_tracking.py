"""Add error tracking columns to reviews table.

Revision ID: 002
Revises: 001
Create Date: 2026-04-15

Adds error_category to classify failure modes (agent_error, buffer_overflow,
json_parse_error, fallback_used, prompt_too_long, etc.) and fallback_model
to record when a secondary model was used.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: str = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Use batch mode and IF NOT EXISTS guard for idempotent upgrades
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = {c["name"] for c in inspector.get_columns("reviews")}

    if "error_category" not in existing_columns:
        op.add_column(
            "reviews",
            sa.Column("error_category", sa.String(50), nullable=True),
        )
    if "fallback_model" not in existing_columns:
        op.add_column(
            "reviews",
            sa.Column("fallback_model", sa.String(100), nullable=True),
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("reviews")}
    if "ix_reviews_error_category" not in existing_indexes:
        op.create_index("ix_reviews_error_category", "reviews", ["error_category"])


def downgrade() -> None:
    op.drop_index("ix_reviews_error_category", table_name="reviews")
    op.drop_column("reviews", "fallback_model")
    op.drop_column("reviews", "error_category")
