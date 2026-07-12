"""Media curation tasks + media visibility (media library curation) (v0.4.8)

Revision ID: 0030_media_curation_tasks
Revises: 0029_media_fingerprints
Create Date: 2026-07-12

Задачи курирования медиатеки (проверить дубли, подтвердить теги, скрыть дубль, заменить
слабое медиа) + поля видимости на media_assets. Теги применяются ТОЛЬКО после подтверждения;
файлы НЕ удаляются; внешнего AI нет; без секретов/внутренних путей. Совместимо со SQLite и
PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0030_media_curation_tasks"
down_revision: str | None = "0029_media_fingerprints"
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
    # --- Поля видимости/курирования на media_assets (v0.4.8) --- #
    op.add_column(
        "media_assets",
        sa.Column(
            "selection_visibility",
            sa.String(length=30),
            nullable=False,
            server_default="selectable",
        ),
    )
    op.add_column(
        "media_assets",
        sa.Column("curation_status", sa.String(length=30), nullable=False, server_default="new"),
    )
    op.add_column(
        "media_assets",
        sa.Column("curation_notes", _json(), nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_media_assets_selection_visibility", "media_assets", ["selection_visibility"]
    )

    # --- Таблица задач курирования --- #
    op.create_table(
        "media_curation_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("media_asset_id", sa.Integer(), nullable=True),
        sa.Column("media_asset_variant_id", sa.Integer(), nullable=True),
        sa.Column("duplicate_cluster_id", sa.Integer(), nullable=True),
        sa.Column("quality_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("fingerprint_id", sa.Integer(), nullable=True),
        sa.Column(
            "task_type", sa.String(length=30), nullable=False, server_default="retag_suggestion"
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="proposed"),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("suggested_action", sa.String(length=40), nullable=True),
        sa.Column("suggested_tags", _json(), nullable=False, server_default="[]"),
        sa.Column("suggested_products", _json(), nullable=False, server_default="[]"),
        sa.Column("suggested_technologies", _json(), nullable=False, server_default="[]"),
        sa.Column("affected_media_asset_ids", _json(), nullable=False, server_default="[]"),
        sa.Column("source_signals", _json(), nullable=False, server_default="[]"),
        sa.Column("risk_flags", _json(), nullable=False, server_default="[]"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("applied_by_user_id", sa.Integer(), nullable=True),
        sa.Column("rejected_by_user_id", sa.Integer(), nullable=True),
        sa.Column("ignored_by_user_id", sa.Integer(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ignored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("task_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_asset_id"], ["media_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["media_asset_variant_id"], ["media_asset_variants.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["duplicate_cluster_id"], ["media_duplicate_clusters.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["quality_snapshot_id"], ["media_quality_snapshots.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["fingerprint_id"], ["media_fingerprints.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["applied_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["rejected_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["ignored_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_media_curation_tasks_idempotency_key",
        "media_curation_tasks",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index("ix_media_curation_tasks_account_id", "media_curation_tasks", ["account_id"])
    op.create_index("ix_media_curation_tasks_project_id", "media_curation_tasks", ["project_id"])
    op.create_index(
        "ix_media_curation_tasks_media_asset_id", "media_curation_tasks", ["media_asset_id"]
    )
    op.create_index(
        "ix_media_curation_tasks_cluster_id", "media_curation_tasks", ["duplicate_cluster_id"]
    )
    op.create_index(
        "ix_media_curation_tasks_quality_id", "media_curation_tasks", ["quality_snapshot_id"]
    )
    op.create_index("ix_media_curation_tasks_task_type", "media_curation_tasks", ["task_type"])
    op.create_index("ix_media_curation_tasks_status", "media_curation_tasks", ["status"])
    op.create_index(
        "ix_media_curation_tasks_confidence", "media_curation_tasks", ["confidence_score"]
    )
    op.create_index("ix_media_curation_tasks_created_at", "media_curation_tasks", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_media_curation_tasks_created_at", table_name="media_curation_tasks")
    op.drop_index("ix_media_curation_tasks_confidence", table_name="media_curation_tasks")
    op.drop_index("ix_media_curation_tasks_status", table_name="media_curation_tasks")
    op.drop_index("ix_media_curation_tasks_task_type", table_name="media_curation_tasks")
    op.drop_index("ix_media_curation_tasks_quality_id", table_name="media_curation_tasks")
    op.drop_index("ix_media_curation_tasks_cluster_id", table_name="media_curation_tasks")
    op.drop_index("ix_media_curation_tasks_media_asset_id", table_name="media_curation_tasks")
    op.drop_index("ix_media_curation_tasks_project_id", table_name="media_curation_tasks")
    op.drop_index("ix_media_curation_tasks_account_id", table_name="media_curation_tasks")
    op.drop_index("ix_media_curation_tasks_idempotency_key", table_name="media_curation_tasks")
    op.drop_table("media_curation_tasks")

    op.drop_index("ix_media_assets_selection_visibility", table_name="media_assets")
    op.drop_column("media_assets", "curation_notes")
    op.drop_column("media_assets", "curation_status")
    op.drop_column("media_assets", "selection_visibility")
