"""external_image_candidates: внешние изображения-кандидаты

Revision ID: 0008_external_image_candidates
Revises: 0007_post_analytics_snapshots
Create Date: 2026-06-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008_external_image_candidates"
down_revision: str | None = "0007_post_analytics_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_image_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("topic_id", sa.Integer(), nullable=True),
        sa.Column("post_id", sa.Integer(), nullable=True),
        sa.Column("query", sa.String(length=512), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("source_url", sa.String(length=1024), nullable=False),
        sa.Column("preview_url", sa.String(length=1024), nullable=True),
        sa.Column("download_url", sa.String(length=1024), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("author_name", sa.String(length=255), nullable=True),
        sa.Column("author_url", sa.String(length=1024), nullable=True),
        sa.Column("license_name", sa.String(length=100), nullable=False),
        sa.Column("license_url", sa.String(length=1024), nullable=True),
        sa.Column("commercial_use_allowed", sa.Boolean(), nullable=False),
        sa.Column("modification_allowed", sa.Boolean(), nullable=False),
        sa.Column("attribution_required", sa.Boolean(), nullable=False),
        sa.Column("contains_people", sa.Boolean(), nullable=False),
        sa.Column("contains_logo", sa.Boolean(), nullable=False),
        sa.Column("safe_for_business", sa.Boolean(), nullable=False),
        sa.Column("forbidden_usage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("review_status", sa.String(length=40), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("media_asset_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["media_asset_id"], ["media_assets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_external_image_candidates_project_id", "external_image_candidates", ["project_id"]
    )
    op.create_index(
        "ix_external_image_candidates_topic_id", "external_image_candidates", ["topic_id"]
    )
    op.create_index(
        "ix_external_image_candidates_post_id", "external_image_candidates", ["post_id"]
    )
    op.create_index(
        "ix_external_image_candidates_provider", "external_image_candidates", ["provider"]
    )
    op.create_index(
        "ix_external_image_candidates_review_status",
        "external_image_candidates",
        ["review_status"],
    )
    op.create_index(
        "ix_external_image_candidates_media_asset_id",
        "external_image_candidates",
        ["media_asset_id"],
    )
    op.create_index(
        "ix_external_image_candidates_provider_source_url",
        "external_image_candidates",
        ["provider", "source_url"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("external_image_candidates")
