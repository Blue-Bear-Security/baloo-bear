"""Add installation_id to all tables for multi-tenant support.

Revision ID: 006
Revises: 005
Create Date: 2026-05-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: str = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = [
    "reviews",
    "findings",
    "review_logs",
    "finding_outcomes",
    "feedback_signals",
]


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    for table in TABLES:
        existing_cols = {c["name"] for c in inspector.get_columns(table)}
        if "installation_id" not in existing_cols:
            op.add_column(table, sa.Column("installation_id", sa.String(255), nullable=True))
            op.create_index(f"ix_{table}_installation_id", table, ["installation_id"])

    # Expand feedback_signals unique constraint to include installation_id so
    # two tenants can share the same (repo, category, pattern) triple.
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("feedback_signals")}
    if "uq_feedback_signals_repo_cat_pattern" in existing_indexes:
        op.drop_index("uq_feedback_signals_repo_cat_pattern", table_name="feedback_signals")
    op.create_index(
        "uq_feedback_signals_repo_cat_pattern",
        "feedback_signals",
        ["repo", "category", "pattern", "installation_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_feedback_signals_repo_cat_pattern", table_name="feedback_signals")
    op.create_index(
        "uq_feedback_signals_repo_cat_pattern",
        "feedback_signals",
        ["repo", "category", "pattern"],
        unique=True,
    )
    for table in reversed(TABLES):
        op.drop_index(f"ix_{table}_installation_id", table_name=table)
        op.drop_column(table, "installation_id")
