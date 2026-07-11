"""Media proxy: временные публичные ссылки на медиа (public_media_links)

Revision ID: 0019_public_media_links
Revises: 0018_platform_connection_fields
Create Date: 2026-07-11

Публичные HTTPS-ссылки на медиа для Instagram (Graph API требует image_url). В БД
хранится только ``token_hash`` (sha256) и короткий ``token_prefix`` — raw-токен не
хранится. Ссылка привязана к account/project/media_asset, ограничена по времени и
отзывается. Совместимо со SQLite (тесты) и PostgreSQL (JSONB variant).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0019_public_media_links"
down_revision: str | None = "0018_platform_connection_fields"
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
        "public_media_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("media_asset_id", sa.Integer(), nullable=False),
        sa.Column("media_asset_variant_id", sa.Integer(), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_prefix", sa.String(length=16), nullable=True),
        sa.Column("purpose", sa.String(length=30), nullable=False, server_default="instagram"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("file_name", sa.String(length=512), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("link_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_asset_id"], ["media_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["media_asset_variant_id"], ["media_asset_variants.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_public_media_links_token_hash", "public_media_links", ["token_hash"], unique=True
    )
    op.create_index("ix_public_media_links_account_id", "public_media_links", ["account_id"])
    op.create_index("ix_public_media_links_project_id", "public_media_links", ["project_id"])
    op.create_index(
        "ix_public_media_links_media_asset_id", "public_media_links", ["media_asset_id"]
    )
    op.create_index("ix_public_media_links_expires_at", "public_media_links", ["expires_at"])
    op.create_index("ix_public_media_links_status", "public_media_links", ["status"])


def downgrade() -> None:
    op.drop_index("ix_public_media_links_status", table_name="public_media_links")
    op.drop_index("ix_public_media_links_expires_at", table_name="public_media_links")
    op.drop_index("ix_public_media_links_media_asset_id", table_name="public_media_links")
    op.drop_index("ix_public_media_links_project_id", table_name="public_media_links")
    op.drop_index("ix_public_media_links_account_id", table_name="public_media_links")
    op.drop_index("ix_public_media_links_token_hash", table_name="public_media_links")
    op.drop_table("public_media_links")
