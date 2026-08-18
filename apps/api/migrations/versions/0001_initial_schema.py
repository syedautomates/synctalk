"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "avatar_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("consent_confirmed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("elevenlabs_voice_id", sa.Text(), nullable=True),
        sa.Column("primary_ref_image_key", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "media_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("avatar_profiles.id"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("s3_key", sa.Text(), nullable=False),
        sa.Column("meta", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("validation", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("validation_errors", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "looks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("avatar_profiles.id"), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("garment_asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("media_assets.id"), nullable=True),
        sa.Column("candidate_keys", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("approved_key", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "video_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("avatar_profiles.id"), nullable=False),
        sa.Column("look_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("looks.id"), nullable=False),
        sa.Column("emotion_brief", sa.Text(), nullable=False),
        sa.Column("script", sa.Text(), nullable=False),
        sa.Column("orchestrator_output", postgresql.JSONB(), nullable=True),
        sa.Column("audio_key", sa.Text(), nullable=True),
        sa.Column("video_720_key", sa.Text(), nullable=True),
        sa.Column("video_4k_key", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("cost_ledger", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("lease_expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("jobs_poll_idx", "jobs", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("jobs_poll_idx", table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("video_requests")
    op.drop_table("looks")
    op.drop_table("media_assets")
    op.drop_table("avatar_profiles")
    op.drop_table("users")
