"""media_asset_variants: производные (улучшенные) копии медиа

Revision ID: 0010_media_asset_variants
Revises: 0009_autonomous_runs
Create Date: 2026-06-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010_media_asset_variants"
down_revision: str | None = "0009_autonomous_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_asset_variants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("media_asset_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("variant_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("source_media_asset_id", sa.Integer(), nullable=True),
        sa.Column("source_path", sa.String(length=1024), nullable=True),
        sa.Column("output_path", sa.String(length=1024), nullable=True),
        sa.Column("output_format", sa.String(length=20), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("operations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("before_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("after_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["media_asset_id"], ["media_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_media_asset_id"], ["media_assets.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_media_asset_variants_media_asset_id", "media_asset_variants", ["media_asset_id"]
    )
    op.create_index("ix_media_asset_variants_project_id", "media_asset_variants", ["project_id"])
    op.create_index("ix_media_asset_variants_status", "media_asset_variants", ["status"])
    op.create_index(
        "ix_media_asset_variants_variant_type", "media_asset_variants", ["variant_type"]
    )


def downgrade() -> None:
    op.drop_table("media_asset_variants")
