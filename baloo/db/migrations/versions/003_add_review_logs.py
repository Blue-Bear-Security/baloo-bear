"""Add review_logs table for execution logging.

Revision ID: 003
Revises: 002
Create Date: 2026-04-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: str = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "review_logs" not in existing_tables:
        op.create_table(
            "review_logs",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column(
                "review_id",
                sa.Integer,
                sa.ForeignKey("reviews.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("event_type", sa.String(50), nullable=False),
            sa.Column("message", sa.Text, nullable=False),
            sa.Column("raw_text", sa.Text, nullable=True),
            sa.Column("metadata_json", sa.Text, nullable=True),
        )
        op.create_index("ix_review_logs_review_created", "review_logs", ["review_id", "created_at"])
        op.create_index("ix_review_logs_created_at", "review_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_review_logs_created_at", table_name="review_logs")
    op.drop_index("ix_review_logs_review_created", table_name="review_logs")
    op.drop_table("review_logs")
