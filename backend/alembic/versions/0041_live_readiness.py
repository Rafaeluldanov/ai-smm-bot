"""Live autopost readiness profiles (v0.5.9)

Revision ID: 0041_live_readiness
Revises: 0040_calendar_plans
Create Date: 2026-07-13

Production live autopost audit: готовность проекта/площадок к реальной автопубликации. Профили НЕ
включают и НЕ обходят глобальные live-флаги; секретов/сырых токенов не хранят. Совместимо со
SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0041_live_readiness"
down_revision: str | None = "0040_calendar_plans"
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
        "project_live_readiness_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("autopilot_profile_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="not_checked"),
        sa.Column("live_mode", sa.String(length=24), nullable=False, server_default="disabled"),
        sa.Column(
            "project_live_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "full_auto_live_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("last_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_check_status", sa.String(length=16), nullable=True),
        sa.Column("readiness_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blockers", _json(), nullable=False, server_default="[]"),
        sa.Column("warnings", _json(), nullable=False, server_default="[]"),
        sa.Column("checklist", _json(), nullable=False, server_default="{}"),
        sa.Column("platform_statuses", _json(), nullable=False, server_default="{}"),
        sa.Column("billing_status", _json(), nullable=False, server_default="{}"),
        sa.Column("media_status", _json(), nullable=False, server_default="{}"),
        sa.Column("schedule_status", _json(), nullable=False, server_default="{}"),
        sa.Column("security_status", _json(), nullable=False, server_default="{}"),
        sa.Column("confirmed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_by_user_id", sa.Integer(), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("profile_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["autopilot_profile_id"], ["project_autopilot_profiles.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["confirmed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["disabled_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_plrp_project_id"),
    )
    op.create_index("ix_plrp_account_id", "project_live_readiness_profiles", ["account_id"])
    op.create_index(
        "ix_plrp_autopilot_profile_id",
        "project_live_readiness_profiles",
        ["autopilot_profile_id"],
    )
    op.create_index("ix_plrp_status", "project_live_readiness_profiles", ["status"])
    op.create_index("ix_plrp_live_mode", "project_live_readiness_profiles", ["live_mode"])
    op.create_index(
        "ix_plrp_project_live_enabled",
        "project_live_readiness_profiles",
        ["project_live_enabled"],
    )
    op.create_index(
        "ix_plrp_full_auto_live_enabled",
        "project_live_readiness_profiles",
        ["full_auto_live_enabled"],
    )
    op.create_index("ix_plrp_last_check_at", "project_live_readiness_profiles", ["last_check_at"])

    op.create_table(
        "platform_live_readiness",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("platform_key", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="not_checked"),
        sa.Column(
            "platform_live_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "credentials_present", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("credentials_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_probe_status", sa.String(length=16), nullable=True),
        sa.Column("last_probe_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("readiness_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blockers", _json(), nullable=False, server_default="[]"),
        sa.Column("warnings", _json(), nullable=False, server_default="[]"),
        sa.Column("required_fields", _json(), nullable=False, server_default="[]"),
        sa.Column("missing_fields", _json(), nullable=False, server_default="[]"),
        sa.Column("capabilities", _json(), nullable=False, server_default="{}"),
        sa.Column("media_requirements", _json(), nullable=False, server_default="{}"),
        sa.Column(
            "confirmation_required", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("confirmed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_by_user_id", sa.Integer(), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("readiness_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["confirmed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["disabled_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "platform_key", name="uq_plr_project_platform"),
    )
    op.create_index("ix_plr_account_id", "platform_live_readiness", ["account_id"])
    op.create_index("ix_plr_project_id", "platform_live_readiness", ["project_id"])
    op.create_index("ix_plr_platform_key", "platform_live_readiness", ["platform_key"])
    op.create_index("ix_plr_status", "platform_live_readiness", ["status"])
    op.create_index(
        "ix_plr_platform_live_enabled", "platform_live_readiness", ["platform_live_enabled"]
    )
    op.create_index("ix_plr_resource_id", "platform_live_readiness", ["resource_id"])
    op.create_index("ix_plr_last_probe_at", "platform_live_readiness", ["last_probe_at"])


def downgrade() -> None:
    op.drop_index("ix_plr_last_probe_at", table_name="platform_live_readiness")
    op.drop_index("ix_plr_resource_id", table_name="platform_live_readiness")
    op.drop_index("ix_plr_platform_live_enabled", table_name="platform_live_readiness")
    op.drop_index("ix_plr_status", table_name="platform_live_readiness")
    op.drop_index("ix_plr_platform_key", table_name="platform_live_readiness")
    op.drop_index("ix_plr_project_id", table_name="platform_live_readiness")
    op.drop_index("ix_plr_account_id", table_name="platform_live_readiness")
    op.drop_table("platform_live_readiness")

    op.drop_index("ix_plrp_last_check_at", table_name="project_live_readiness_profiles")
    op.drop_index("ix_plrp_full_auto_live_enabled", table_name="project_live_readiness_profiles")
    op.drop_index("ix_plrp_project_live_enabled", table_name="project_live_readiness_profiles")
    op.drop_index("ix_plrp_live_mode", table_name="project_live_readiness_profiles")
    op.drop_index("ix_plrp_status", table_name="project_live_readiness_profiles")
    op.drop_index("ix_plrp_autopilot_profile_id", table_name="project_live_readiness_profiles")
    op.drop_index("ix_plrp_account_id", table_name="project_live_readiness_profiles")
    op.drop_table("project_live_readiness_profiles")
