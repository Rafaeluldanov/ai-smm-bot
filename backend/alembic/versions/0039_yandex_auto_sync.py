"""Yandex Disk auto-sync (v0.5.7)

Revision ID: 0039_yandex_auto_sync
Revises: 0038_autopilot_profile
Create Date: 2026-07-13

Профиль авто-синхронизации Яндекс Диска (одна панель на проект) + история прогонов. Секретов/
сырых токенов/путей не хранит; реальной сети/удаления файлов нет (за флагами). Совместимо со
SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0039_yandex_auto_sync"
down_revision: str | None = "0038_autopilot_profile"
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
        "project_yandex_sync_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("autopilot_profile_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ready"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "source_type", sa.String(length=24), nullable=False, server_default="public_disk_url"
        ),
        sa.Column("public_url", sa.Text(), nullable=True),
        sa.Column("root_folder", sa.String(length=255), nullable=True),
        sa.Column("default_tags", _json(), nullable=False, server_default="[]"),
        sa.Column("allowed_folders", _json(), nullable=False, server_default="[]"),
        sa.Column("sync_frequency_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(length=24), nullable=True),
        sa.Column("last_sync_summary", _json(), nullable=False, server_default="{}"),
        sa.Column("next_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("media_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("image_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("video_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_media_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_media_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_media_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_blockers", _json(), nullable=False, server_default="[]"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("profile_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["autopilot_profile_id"], ["project_autopilot_profiles.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_yandex_sync_project_id"),
    )
    op.create_index("ix_pysp_account_id", "project_yandex_sync_profiles", ["account_id"])
    op.create_index("ix_pysp_project_id", "project_yandex_sync_profiles", ["project_id"])
    op.create_index(
        "ix_pysp_autopilot_profile_id", "project_yandex_sync_profiles", ["autopilot_profile_id"]
    )
    op.create_index("ix_pysp_status", "project_yandex_sync_profiles", ["status"])
    op.create_index("ix_pysp_is_enabled", "project_yandex_sync_profiles", ["is_enabled"])
    op.create_index("ix_pysp_next_sync_at", "project_yandex_sync_profiles", ["next_sync_at"])
    op.create_index("ix_pysp_last_sync_at", "project_yandex_sync_profiles", ["last_sync_at"])

    op.create_table(
        "yandex_auto_sync_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("sync_profile_id", sa.Integer(), nullable=True),
        sa.Column("autopilot_profile_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="preview"),
        sa.Column(
            "source_type", sa.String(length=24), nullable=False, server_default="public_disk_url"
        ),
        sa.Column("public_url_masked", sa.String(length=255), nullable=True),
        sa.Column("root_folder", sa.String(length=255), nullable=True),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("files_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("files_imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("files_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("files_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("files_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("media_assets_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("media_assets_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quality_snapshots_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fingerprints_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("curation_tasks_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blockers", _json(), nullable=False, server_default="[]"),
        sa.Column("warnings", _json(), nullable=False, server_default="[]"),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("run_metadata", _json(), nullable=False, server_default="{}"),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_worker_owner_id", sa.String(length=128), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["sync_profile_id"], ["project_yandex_sync_profiles.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["autopilot_profile_id"], ["project_autopilot_profiles.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_yandex_sync_run_idem"),
    )
    op.create_index("ix_yasr_account_id", "yandex_auto_sync_runs", ["account_id"])
    op.create_index("ix_yasr_project_id", "yandex_auto_sync_runs", ["project_id"])
    op.create_index("ix_yasr_sync_profile_id", "yandex_auto_sync_runs", ["sync_profile_id"])
    op.create_index("ix_yasr_status", "yandex_auto_sync_runs", ["status"])
    op.create_index("ix_yasr_dry_run", "yandex_auto_sync_runs", ["dry_run"])
    op.create_index("ix_yasr_started_at", "yandex_auto_sync_runs", ["started_at"])
    op.create_index("ix_yasr_created_at", "yandex_auto_sync_runs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_yasr_created_at", table_name="yandex_auto_sync_runs")
    op.drop_index("ix_yasr_started_at", table_name="yandex_auto_sync_runs")
    op.drop_index("ix_yasr_dry_run", table_name="yandex_auto_sync_runs")
    op.drop_index("ix_yasr_status", table_name="yandex_auto_sync_runs")
    op.drop_index("ix_yasr_sync_profile_id", table_name="yandex_auto_sync_runs")
    op.drop_index("ix_yasr_project_id", table_name="yandex_auto_sync_runs")
    op.drop_index("ix_yasr_account_id", table_name="yandex_auto_sync_runs")
    op.drop_table("yandex_auto_sync_runs")

    op.drop_index("ix_pysp_last_sync_at", table_name="project_yandex_sync_profiles")
    op.drop_index("ix_pysp_next_sync_at", table_name="project_yandex_sync_profiles")
    op.drop_index("ix_pysp_is_enabled", table_name="project_yandex_sync_profiles")
    op.drop_index("ix_pysp_status", table_name="project_yandex_sync_profiles")
    op.drop_index("ix_pysp_autopilot_profile_id", table_name="project_yandex_sync_profiles")
    op.drop_index("ix_pysp_project_id", table_name="project_yandex_sync_profiles")
    op.drop_index("ix_pysp_account_id", table_name="project_yandex_sync_profiles")
    op.drop_table("project_yandex_sync_profiles")
