"""Project autopilot profile (v0.5.6)

Revision ID: 0038_autopilot_profile
Revises: 0037_telegram_updates
Create Date: 2026-07-13

«Панель автопилота» проекта: упрощённые клиентские настройки (площадки/Яндекс Диск/календарь/
правила) поверх CrmPublishingPlan. Секретов/сырых токенов не хранит. Один профиль на проект
(project_id unique). Совместимо со SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0038_autopilot_profile"
down_revision: str | None = "0037_telegram_updates"
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
        "project_autopilot_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="setup_required"),
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="full_auto"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("yandex_resource_id", sa.Integer(), nullable=True),
        sa.Column("primary_platforms", _json(), nullable=False, server_default="[]"),
        sa.Column("calendar_rules", _json(), nullable=False, server_default="{}"),
        sa.Column("content_rules", _json(), nullable=False, server_default="{}"),
        sa.Column("quality_rules", _json(), nullable=False, server_default="{}"),
        sa.Column("safety_rules", _json(), nullable=False, server_default="{}"),
        sa.Column("setup_progress", _json(), nullable=False, server_default="{}"),
        sa.Column("active_blockers", _json(), nullable=False, server_default="[]"),
        sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_health_status", sa.String(length=24), nullable=True),
        sa.Column("last_autopilot_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_planned_post_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("profile_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_autopilot_project_id"),
    )
    op.create_index("ix_pap_account_id", "project_autopilot_profiles", ["account_id"])
    op.create_index("ix_pap_project_id", "project_autopilot_profiles", ["project_id"])
    op.create_index("ix_pap_status", "project_autopilot_profiles", ["status"])
    op.create_index("ix_pap_mode", "project_autopilot_profiles", ["mode"])
    op.create_index("ix_pap_is_enabled", "project_autopilot_profiles", ["is_enabled"])
    op.create_index(
        "ix_pap_next_planned_post_at", "project_autopilot_profiles", ["next_planned_post_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_pap_next_planned_post_at", table_name="project_autopilot_profiles")
    op.drop_index("ix_pap_is_enabled", table_name="project_autopilot_profiles")
    op.drop_index("ix_pap_mode", table_name="project_autopilot_profiles")
    op.drop_index("ix_pap_status", table_name="project_autopilot_profiles")
    op.drop_index("ix_pap_project_id", table_name="project_autopilot_profiles")
    op.drop_index("ix_pap_account_id", table_name="project_autopilot_profiles")
    op.drop_table("project_autopilot_profiles")
