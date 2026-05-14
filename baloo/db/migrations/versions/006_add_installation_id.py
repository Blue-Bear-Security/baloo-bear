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

    # Replace the single (repo, category, pattern) unique index with two partial
    # indexes so both single-tenant (NULL) and multi-tenant (non-NULL) rows
    # enforce uniqueness correctly.  PostgreSQL treats NULLs as distinct in
    # ordinary unique indexes, so a 4-column index including the nullable
    # installation_id would silently stop enforcing uniqueness for NULL rows.
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("feedback_signals")}
    for old in ("uq_feedback_signals_repo_cat_pattern",):
        if old in existing_indexes:
            op.drop_index(old, table_name="feedback_signals")

    if "uq_feedback_signals_null_tenant" not in existing_indexes:
        op.create_index(
            "uq_feedback_signals_null_tenant",
            "feedback_signals",
            ["repo", "category", "pattern"],
            unique=True,
            postgresql_where=sa.text("installation_id IS NULL"),
            sqlite_where=sa.text("installation_id IS NULL"),
        )
    if "uq_feedback_signals_with_tenant" not in existing_indexes:
        op.create_index(
            "uq_feedback_signals_with_tenant",
            "feedback_signals",
            ["repo", "category", "pattern", "installation_id"],
            unique=True,
            postgresql_where=sa.text("installation_id IS NOT NULL"),
            sqlite_where=sa.text("installation_id IS NOT NULL"),
        )


def downgrade() -> None:
    op.drop_index("uq_feedback_signals_with_tenant", table_name="feedback_signals")
    op.drop_index("uq_feedback_signals_null_tenant", table_name="feedback_signals")
    op.create_index(
        "uq_feedback_signals_repo_cat_pattern",
        "feedback_signals",
        ["repo", "category", "pattern"],
        unique=True,
    )
    for table in reversed(TABLES):
        op.drop_index(f"ix_{table}_installation_id", table_name=table)
        op.drop_column(table, "installation_id")
