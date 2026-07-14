"""Live autopilot monitoring: snapshots + incidents (v0.6.1)

Revision ID: 0043_live_autopilot_monitoring
Revises: 0042_live_publish_attempts
Create Date: 2026-07-13

Мониторинг live-автопилота: снимки состояния + инциденты. Секретов/сырых токенов не хранит;
kill switch управляет только состоянием в БД, глобальные live-флаги не трогает. Совместимо со
SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0043_live_autopilot_monitoring"
down_revision: str | None = "0042_live_publish_attempts"
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
        "live_autopilot_monitor_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("platform_key", sa.String(length=32), nullable=True),
        sa.Column("health_status", sa.String(length=16), nullable=False, server_default="unknown"),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("published_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("failure_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("last_attempt_id", sa.Integer(), nullable=True),
        sa.Column("last_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_blocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("open_incident_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("critical_incident_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("balance_units", sa.Integer(), nullable=True),
        sa.Column("approx_posts_left", sa.Integer(), nullable=True),
        sa.Column(
            "project_live_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "full_auto_live_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("platform_live_statuses", _json(), nullable=False, server_default="{}"),
        sa.Column("readiness_status", _json(), nullable=False, server_default="{}"),
        sa.Column("blockers", _json(), nullable=False, server_default="[]"),
        sa.Column("warnings", _json(), nullable=False, server_default="[]"),
        sa.Column("summary", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lams_account_id", "live_autopilot_monitor_snapshots", ["account_id"])
    op.create_index("ix_lams_project_id", "live_autopilot_monitor_snapshots", ["project_id"])
    op.create_index("ix_lams_platform_key", "live_autopilot_monitor_snapshots", ["platform_key"])
    op.create_index("ix_lams_health_status", "live_autopilot_monitor_snapshots", ["health_status"])
    op.create_index("ix_lams_created_at", "live_autopilot_monitor_snapshots", ["created_at"])

    op.create_table(
        "live_autopilot_incidents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("platform_key", sa.String(length=32), nullable=True),
        sa.Column("incident_type", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source_entity_type", sa.String(length=48), nullable=True),
        sa.Column("source_entity_id", sa.String(length=64), nullable=True),
        sa.Column("live_publish_attempt_id", sa.Integer(), nullable=True),
        sa.Column("post_id", sa.Integer(), nullable=True),
        sa.Column("publication_id", sa.Integer(), nullable=True),
        sa.Column("schedule_run_id", sa.Integer(), nullable=True),
        sa.Column("autopilot_run_id", sa.Integer(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("occurrences", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("acknowledged_by_user_id", sa.Integer(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_user_id", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ignored_by_user_id", sa.Integer(), nullable=True),
        sa.Column("ignored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_paused", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("auto_pause_reason", sa.String(length=64), nullable=True),
        sa.Column("recommended_action", sa.String(length=255), nullable=True),
        sa.Column("incident_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["acknowledged_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["ignored_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lai_account_id", "live_autopilot_incidents", ["account_id"])
    op.create_index("ix_lai_project_id", "live_autopilot_incidents", ["project_id"])
    op.create_index("ix_lai_platform_key", "live_autopilot_incidents", ["platform_key"])
    op.create_index("ix_lai_incident_type", "live_autopilot_incidents", ["incident_type"])
    op.create_index("ix_lai_status", "live_autopilot_incidents", ["status"])
    op.create_index("ix_lai_severity", "live_autopilot_incidents", ["severity"])
    op.create_index(
        "ix_lai_live_publish_attempt_id", "live_autopilot_incidents", ["live_publish_attempt_id"]
    )
    op.create_index("ix_lai_post_id", "live_autopilot_incidents", ["post_id"])
    op.create_index("ix_lai_publication_id", "live_autopilot_incidents", ["publication_id"])
    op.create_index("ix_lai_last_seen_at", "live_autopilot_incidents", ["last_seen_at"])
    op.create_index("ix_lai_created_at", "live_autopilot_incidents", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_lai_created_at", table_name="live_autopilot_incidents")
    op.drop_index("ix_lai_last_seen_at", table_name="live_autopilot_incidents")
    op.drop_index("ix_lai_publication_id", table_name="live_autopilot_incidents")
    op.drop_index("ix_lai_post_id", table_name="live_autopilot_incidents")
    op.drop_index("ix_lai_live_publish_attempt_id", table_name="live_autopilot_incidents")
    op.drop_index("ix_lai_severity", table_name="live_autopilot_incidents")
    op.drop_index("ix_lai_status", table_name="live_autopilot_incidents")
    op.drop_index("ix_lai_incident_type", table_name="live_autopilot_incidents")
    op.drop_index("ix_lai_platform_key", table_name="live_autopilot_incidents")
    op.drop_index("ix_lai_project_id", table_name="live_autopilot_incidents")
    op.drop_index("ix_lai_account_id", table_name="live_autopilot_incidents")
    op.drop_table("live_autopilot_incidents")

    op.drop_index("ix_lams_created_at", table_name="live_autopilot_monitor_snapshots")
    op.drop_index("ix_lams_health_status", table_name="live_autopilot_monitor_snapshots")
    op.drop_index("ix_lams_platform_key", table_name="live_autopilot_monitor_snapshots")
    op.drop_index("ix_lams_project_id", table_name="live_autopilot_monitor_snapshots")
    op.drop_index("ix_lams_account_id", table_name="live_autopilot_monitor_snapshots")
    op.drop_table("live_autopilot_monitor_snapshots")
