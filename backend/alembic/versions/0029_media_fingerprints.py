"""Media fingerprints + duplicate clusters (visual dedup) (v0.4.7)

Revision ID: 0029_media_fingerprints
Revises: 0028_media_quality_snapshots
Create Date: 2026-07-12

Безопасные локальные fingerprint медиа (sha256/perceptual/average/difference hash + сигнатуры)
и кластеры дублей (canonical + members + similarity). Без raw bytes, внутренних путей и
секретов; без внешнего AI. Совместимо со SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0029_media_fingerprints"
down_revision: str | None = "0028_media_quality_snapshots"
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
        "media_fingerprints",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("media_asset_id", sa.Integer(), nullable=False),
        sa.Column("media_asset_variant_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="unavailable"),
        sa.Column("file_sha256", sa.String(length=64), nullable=True),
        sa.Column("perceptual_hash", sa.String(length=64), nullable=True),
        sa.Column("average_hash", sa.String(length=64), nullable=True),
        sa.Column("difference_hash", sa.String(length=64), nullable=True),
        sa.Column("color_signature", _json(), nullable=False, server_default="{}"),
        sa.Column("dimension_signature", _json(), nullable=False, server_default="{}"),
        sa.Column("metadata_signature", _json(), nullable=False, server_default="{}"),
        sa.Column("tag_signature", _json(), nullable=False, server_default="{}"),
        sa.Column("fingerprint_metadata", _json(), nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_asset_id"], ["media_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["media_asset_variant_id"], ["media_asset_variants.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_media_fingerprints_account_id", "media_fingerprints", ["account_id"])
    op.create_index("ix_media_fingerprints_project_id", "media_fingerprints", ["project_id"])
    op.create_index(
        "ix_media_fingerprints_media_asset_id", "media_fingerprints", ["media_asset_id"]
    )
    op.create_index(
        "ix_media_fingerprints_variant_id", "media_fingerprints", ["media_asset_variant_id"]
    )
    op.create_index("ix_media_fingerprints_status", "media_fingerprints", ["status"])
    op.create_index("ix_media_fingerprints_file_sha256", "media_fingerprints", ["file_sha256"])
    op.create_index(
        "ix_media_fingerprints_perceptual_hash", "media_fingerprints", ["perceptual_hash"]
    )
    op.create_index("ix_media_fingerprints_created_at", "media_fingerprints", ["created_at"])

    op.create_table(
        "media_duplicate_clusters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("cluster_type", sa.String(length=30), nullable=False, server_default="unknown"),
        sa.Column("canonical_media_asset_id", sa.Integer(), nullable=True),
        sa.Column("member_media_asset_ids", _json(), nullable=False, server_default="[]"),
        sa.Column("member_fingerprint_ids", _json(), nullable=False, server_default="[]"),
        sa.Column("similarity_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reasons", _json(), nullable=False, server_default="[]"),
        sa.Column("recommended_actions", _json(), nullable=False, server_default="[]"),
        sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cluster_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["canonical_media_asset_id"], ["media_assets.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_media_duplicate_clusters_project_id", "media_duplicate_clusters", ["project_id"]
    )
    op.create_index("ix_media_duplicate_clusters_status", "media_duplicate_clusters", ["status"])
    op.create_index(
        "ix_media_duplicate_clusters_cluster_type", "media_duplicate_clusters", ["cluster_type"]
    )
    op.create_index(
        "ix_media_duplicate_clusters_canonical",
        "media_duplicate_clusters",
        ["canonical_media_asset_id"],
    )
    op.create_index(
        "ix_media_duplicate_clusters_similarity",
        "media_duplicate_clusters",
        ["similarity_score"],
    )
    op.create_index(
        "ix_media_duplicate_clusters_created_at", "media_duplicate_clusters", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_media_duplicate_clusters_created_at", table_name="media_duplicate_clusters")
    op.drop_index("ix_media_duplicate_clusters_similarity", table_name="media_duplicate_clusters")
    op.drop_index("ix_media_duplicate_clusters_canonical", table_name="media_duplicate_clusters")
    op.drop_index("ix_media_duplicate_clusters_cluster_type", table_name="media_duplicate_clusters")
    op.drop_index("ix_media_duplicate_clusters_status", table_name="media_duplicate_clusters")
    op.drop_index("ix_media_duplicate_clusters_project_id", table_name="media_duplicate_clusters")
    op.drop_table("media_duplicate_clusters")

    op.drop_index("ix_media_fingerprints_created_at", table_name="media_fingerprints")
    op.drop_index("ix_media_fingerprints_perceptual_hash", table_name="media_fingerprints")
    op.drop_index("ix_media_fingerprints_file_sha256", table_name="media_fingerprints")
    op.drop_index("ix_media_fingerprints_status", table_name="media_fingerprints")
    op.drop_index("ix_media_fingerprints_variant_id", table_name="media_fingerprints")
    op.drop_index("ix_media_fingerprints_media_asset_id", table_name="media_fingerprints")
    op.drop_index("ix_media_fingerprints_project_id", table_name="media_fingerprints")
    op.drop_index("ix_media_fingerprints_account_id", table_name="media_fingerprints")
    op.drop_table("media_fingerprints")
