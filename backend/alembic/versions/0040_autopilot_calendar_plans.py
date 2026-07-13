"""Autopilot calendar plans (v0.5.8)

Revision ID: 0040_calendar_plans
Revises: 0039_yandex_auto_sync
Create Date: 2026-07-13

Клиентский календарь автопостинга (Calendar Assistant) — понятный слой поверх CrmPublishingPlan.
Секретов/сырых токенов не хранит; применение календаря не публикует и не включает live-флаги.
Совместимо со SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0040_calendar_plans"
down_revision: str | None = "0039_yandex_auto_sync"
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
        "autopilot_calendar_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("autopilot_profile_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("preset", sa.String(length=24), nullable=False, server_default="three_per_week"),
        sa.Column("goal", sa.String(length=16), nullable=False, server_default="mixed"),
        sa.Column("platforms", _json(), nullable=False, server_default="[]"),
        sa.Column("weekdays", _json(), nullable=False, server_default="[]"),
        sa.Column("publish_times", _json(), nullable=False, server_default="[]"),
        sa.Column("posts_per_day", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Europe/Moscow"),
        sa.Column("start_date", sa.String(length=32), nullable=True),
        sa.Column("end_date", sa.String(length=32), nullable=True),
        sa.Column(
            "time_strategy", sa.String(length=24), nullable=False, server_default="platform_default"
        ),
        sa.Column("generated_rules", _json(), nullable=False, server_default="{}"),
        sa.Column("source_signals", _json(), nullable=False, server_default="{}"),
        sa.Column("risk_flags", _json(), nullable=False, server_default="[]"),
        sa.Column("estimated_posts_per_month", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_units_per_month", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_media_needed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("linked_publishing_plan_ids", _json(), nullable=False, server_default="[]"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("plan_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["autopilot_profile_id"], ["project_autopilot_profiles.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_acp_account_id", "autopilot_calendar_plans", ["account_id"])
    op.create_index("ix_acp_project_id", "autopilot_calendar_plans", ["project_id"])
    op.create_index(
        "ix_acp_autopilot_profile_id", "autopilot_calendar_plans", ["autopilot_profile_id"]
    )
    op.create_index("ix_acp_status", "autopilot_calendar_plans", ["status"])
    op.create_index("ix_acp_preset", "autopilot_calendar_plans", ["preset"])
    op.create_index("ix_acp_goal", "autopilot_calendar_plans", ["goal"])
    op.create_index("ix_acp_created_at", "autopilot_calendar_plans", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_acp_created_at", table_name="autopilot_calendar_plans")
    op.drop_index("ix_acp_goal", table_name="autopilot_calendar_plans")
    op.drop_index("ix_acp_preset", table_name="autopilot_calendar_plans")
    op.drop_index("ix_acp_status", table_name="autopilot_calendar_plans")
    op.drop_index("ix_acp_autopilot_profile_id", table_name="autopilot_calendar_plans")
    op.drop_index("ix_acp_project_id", table_name="autopilot_calendar_plans")
    op.drop_index("ix_acp_account_id", table_name="autopilot_calendar_plans")
    op.drop_table("autopilot_calendar_plans")
