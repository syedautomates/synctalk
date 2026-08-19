"""add idempotency_keys table

M7 hardening (claude.md section 7): "Idempotency keys on all POSTs". Scoped in practice
to the real-cost/side-effecting POSTs (voice clone, look generation, video creation) --
see DECISIONS.md's M7 entry for the reasoning. Table is generic so any route can adopt it.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-19

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("key", "endpoint"),
    )


def downgrade() -> None:
    op.drop_table("idempotency_keys")
