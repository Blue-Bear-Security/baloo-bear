"""Add partial unique index to enforce one active review per PR.

Revision ID: 006
Revises: 005
Create Date: 2026-05-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: str = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    indexes = {idx["name"] for idx in inspector.get_indexes("reviews")}

    if "uq_reviews_active_sha" not in indexes:
        # Abandon any reviews that are currently in_progress — they are orphaned
        # from a previous process and can never complete.
        conn.execute(
            sa.text(
                "UPDATE reviews SET review_status = 'error', "
                "error_message = 'stale: abandoned review cleared on upgrade' "
                "WHERE review_status = 'in_progress'"
            )
        )
        conn.execute(
            sa.text(
                "CREATE UNIQUE INDEX uq_reviews_active_sha "
                "ON reviews (repo_full_name, pr_number, commit_sha) "
                "WHERE review_status = 'in_progress'"
            )
        )


def downgrade() -> None:
    op.drop_index("uq_reviews_active_sha", table_name="reviews")
