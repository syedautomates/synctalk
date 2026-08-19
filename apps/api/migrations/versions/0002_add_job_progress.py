"""add jobs.progress column

`claude.md` section 5's literal jobs schema has no progress column, but section 6's worker
protocol (`PATCH /internal/jobs/{id} {progress}`) and `GET /jobs/{id}` (UI polling, 0-100)
both require one. Storing it in `result` would conflate final job output with interim
state, so it gets its own column. See DECISIONS.md M3 entry.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-19

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("jobs", "progress")
