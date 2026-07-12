"""Media quality snapshots (media quality scoring) (v0.4.6)

Revision ID: 0028_media_quality_snapshots
Revises: 0027_schedule_media_decisions
Create Date: 2026-07-12

Снимок оценки качества медиа — «насколько медиа сильное/уникальное/пригодное к платформе».
Правило-ориентированная оценка, без внешнего AI и без live-публикаций; секретов и внутренних
путей к файлам в payload нет. Совместимо со SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0028_media_quality_snapshots"
down_revision: str | None = "0027_schedule_media_decisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
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
    )


def upgrade() -> None:
    op.create_table(
        "media_quality_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("media_asset_id", sa.Integer(), nullable=False),
        sa.Column("media_asset_variant_id", sa.Integer(), nullable=True),
        sa.Column("platform_key", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("quality_score", sa.Integer(), nullable=True),
        sa.Column("relevance_score", sa.Integer(), nullable=True),
        sa.Column("freshness_score", sa.Integer(), nullable=True),
        sa.Column("uniqueness_score", sa.Integer(), nullable=True),
        sa.Column("platform_fit_score", sa.Integer(), nullable=True),
        sa.Column("overall_score", sa.Integer(), nullable=True),
        sa.Column("issue_codes", _json(), nullable=False, server_default="[]"),
        sa.Column("positive_signals", _json(), nullable=False, server_default="[]"),
        sa.Column("negative_signals", _json(), nullable=False, server_default="[]"),
        sa.Column("duplicate_of_media_asset_id", sa.Integer(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recent_usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recommended_tags", _json(), nullable=False, server_default="[]"),
        sa.Column("recommended_actions", _json(), nullable=False, server_default="[]"),
        sa.Column("source_signals", _json(), nullable=False, server_default="[]"),
        sa.Column("snapshot_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_asset_id"], ["media_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["media_asset_variant_id"], ["media_asset_variants.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["duplicate_of_media_asset_id"], ["media_assets.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_media_quality_snapshots_account_id", "media_quality_snapshots", ["account_id"]
    )
    op.create_index(
        "ix_media_quality_snapshots_project_id", "media_quality_snapshots", ["project_id"]
    )
    op.create_index(
        "ix_media_quality_snapshots_media_asset_id", "media_quality_snapshots", ["media_asset_id"]
    )
    op.create_index(
        "ix_media_quality_snapshots_platform_key", "media_quality_snapshots", ["platform_key"]
    )
    op.create_index("ix_media_quality_snapshots_status", "media_quality_snapshots", ["status"])
    op.create_index(
        "ix_media_quality_snapshots_overall_score", "media_quality_snapshots", ["overall_score"]
    )
    op.create_index(
        "ix_media_quality_snapshots_duplicate_of",
        "media_quality_snapshots",
        ["duplicate_of_media_asset_id"],
    )
    op.create_index(
        "ix_media_quality_snapshots_created_at", "media_quality_snapshots", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_media_quality_snapshots_created_at", table_name="media_quality_snapshots")
    op.drop_index("ix_media_quality_snapshots_duplicate_of", table_name="media_quality_snapshots")
    op.drop_index("ix_media_quality_snapshots_overall_score", table_name="media_quality_snapshots")
    op.drop_index("ix_media_quality_snapshots_status", table_name="media_quality_snapshots")
    op.drop_index("ix_media_quality_snapshots_platform_key", table_name="media_quality_snapshots")
    op.drop_index("ix_media_quality_snapshots_media_asset_id", table_name="media_quality_snapshots")
    op.drop_index("ix_media_quality_snapshots_project_id", table_name="media_quality_snapshots")
    op.drop_index("ix_media_quality_snapshots_account_id", table_name="media_quality_snapshots")
    op.drop_table("media_quality_snapshots")
