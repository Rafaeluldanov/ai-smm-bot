"""Media proxy delivery layer: transforms, limits, access logs (v0.6.2)

Revision ID: 0044_media_proxy_layer
Revises: 0043_live_autopilot_monitoring
Create Date: 2026-07-14

Расширяет media-proxy: колонки token_type/transform/max_requests на public_media_links,
proxy_ready/last_proxy_generated_at на media_assets, новая таблица media_proxy_access_logs
(аналитика доставки, только хеши IP/UA). Секретов/сырых токенов не хранит. SQLite+PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0044_media_proxy_layer"
down_revision: str | None = "0043_live_autopilot_monitoring"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # public_media_links: тип токена, трансформация, лимит запросов.
    op.add_column(
        "public_media_links",
        sa.Column("token_type", sa.String(length=20), nullable=False, server_default="image"),
    )
    op.add_column(
        "public_media_links",
        sa.Column("transform", sa.String(length=30), nullable=False, server_default="original"),
    )
    op.add_column(
        "public_media_links",
        sa.Column("max_requests", sa.Integer(), nullable=True),
    )

    # media_assets: признак и время генерации публичной ссылки доставки.
    op.add_column(
        "media_assets",
        sa.Column("proxy_ready", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "media_assets",
        sa.Column("last_proxy_generated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # media_proxy_access_logs: аналитика обращений (без IP/UA/секретов).
    op.create_table(
        "media_proxy_access_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_media_link_id", sa.Integer(), nullable=True),
        sa.Column("media_asset_id", sa.Integer(), nullable=True),
        sa.Column("request_ip_hash", sa.String(length=64), nullable=True),
        sa.Column("user_agent_hash", sa.String(length=64), nullable=True),
        sa.Column("status", sa.Integer(), nullable=False, server_default="200"),
        sa.Column("response_type", sa.String(length=100), nullable=True),
        sa.Column("response_size", sa.Integer(), nullable=True),
        sa.Column("transform", sa.String(length=30), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["public_media_link_id"], ["public_media_links.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mpal_public_media_link_id", "media_proxy_access_logs", ["public_media_link_id"]
    )
    op.create_index("ix_mpal_media_asset_id", "media_proxy_access_logs", ["media_asset_id"])
    op.create_index("ix_mpal_status", "media_proxy_access_logs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_mpal_status", table_name="media_proxy_access_logs")
    op.drop_index("ix_mpal_media_asset_id", table_name="media_proxy_access_logs")
    op.drop_index("ix_mpal_public_media_link_id", table_name="media_proxy_access_logs")
    op.drop_table("media_proxy_access_logs")

    op.drop_column("media_assets", "last_proxy_generated_at")
    op.drop_column("media_assets", "proxy_ready")

    op.drop_column("public_media_links", "max_requests")
    op.drop_column("public_media_links", "transform")
    op.drop_column("public_media_links", "token_type")
