"""Add finding_outcomes table for tracking review quality.

Revision ID: 004
Revises: 003
Create Date: 2026-04-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: str = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "finding_outcomes" not in existing_tables:
        op.create_table(
            "finding_outcomes",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column(
                "finding_id",
                sa.Integer,
                sa.ForeignKey("findings.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "review_id",
                sa.Integer,
                sa.ForeignKey("reviews.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("repo_full_name", sa.String(255), nullable=False),
            sa.Column("pr_number", sa.Integer, nullable=False),
            sa.Column("outcome", sa.String(20), nullable=False),
            sa.Column("signals", sa.JSON, nullable=True),
            sa.Column("labeled_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_finding_outcomes_finding_id", "finding_outcomes", ["finding_id"], unique=True
        )
        op.create_index("ix_finding_outcomes_review_id", "finding_outcomes", ["review_id"])
        op.create_index("ix_finding_outcomes_repo", "finding_outcomes", ["repo_full_name"])
        op.create_index("ix_finding_outcomes_outcome", "finding_outcomes", ["outcome"])


def downgrade() -> None:
    op.drop_index("ix_finding_outcomes_outcome", table_name="finding_outcomes")
    op.drop_index("ix_finding_outcomes_repo", table_name="finding_outcomes")
    op.drop_index("ix_finding_outcomes_review_id", table_name="finding_outcomes")
    op.drop_index("ix_finding_outcomes_finding_id", table_name="finding_outcomes")
    op.drop_table("finding_outcomes")
