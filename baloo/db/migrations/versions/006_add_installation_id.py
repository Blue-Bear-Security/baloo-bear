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


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_index(f"ix_{table}_installation_id", table_name=table)
        op.drop_column(table, "installation_id")
