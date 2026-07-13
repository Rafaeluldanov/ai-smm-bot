"""Live publish attempts (v0.6.0, Telegram-first live rollout)

Revision ID: 0042_live_publish_attempts
Revises: 0041_live_readiness
Create Date: 2026-07-13

Журнал live/dry-run попыток публикации автопилота (Telegram-first). Секретов/сырых токенов не
хранит; заблокированная/dry-run попытка не списывает деньги. Совместимо со SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0042_live_publish_attempts"
down_revision: str | None = "0041_live_readiness"
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
        "live_publish_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("platform_key", sa.String(length=32), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=True),
        sa.Column("publication_id", sa.Integer(), nullable=True),
        sa.Column("schedule_run_id", sa.Integer(), nullable=True),
        sa.Column("autopilot_run_id", sa.Integer(), nullable=True),
        sa.Column("readiness_profile_id", sa.Integer(), nullable=True),
        sa.Column("platform_readiness_id", sa.Integer(), nullable=True),
        sa.Column("trigger", sa.String(length=24), nullable=False, server_default="manual_preview"),
        sa.Column("mode", sa.String(length=24), nullable=False, server_default="dry_run"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="preview"),
        sa.Column(
            "global_live_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "project_live_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "platform_live_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "full_auto_live_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("readiness_ready", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("balance_ok", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("live_attempted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("external_post_id", sa.String(length=128), nullable=True),
        sa.Column("external_url", sa.String(length=512), nullable=True),
        sa.Column("request_summary", _json(), nullable=False, server_default="{}"),
        sa.Column("response_summary", _json(), nullable=False, server_default="{}"),
        sa.Column("blockers", _json(), nullable=False, server_default="[]"),
        sa.Column("warnings", _json(), nullable=False, server_default="[]"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("confirmed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["confirmed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_lpa_idempotency_key"),
    )
    op.create_index("ix_lpa_account_id", "live_publish_attempts", ["account_id"])
    op.create_index("ix_lpa_project_id", "live_publish_attempts", ["project_id"])
    op.create_index("ix_lpa_platform_key", "live_publish_attempts", ["platform_key"])
    op.create_index("ix_lpa_post_id", "live_publish_attempts", ["post_id"])
    op.create_index("ix_lpa_publication_id", "live_publish_attempts", ["publication_id"])
    op.create_index("ix_lpa_schedule_run_id", "live_publish_attempts", ["schedule_run_id"])
    op.create_index("ix_lpa_trigger", "live_publish_attempts", ["trigger"])
    op.create_index("ix_lpa_mode", "live_publish_attempts", ["mode"])
    op.create_index("ix_lpa_status", "live_publish_attempts", ["status"])
    op.create_index("ix_lpa_idempotency_key", "live_publish_attempts", ["idempotency_key"])
    op.create_index("ix_lpa_started_at", "live_publish_attempts", ["started_at"])
    op.create_index("ix_lpa_created_at", "live_publish_attempts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_lpa_created_at", table_name="live_publish_attempts")
    op.drop_index("ix_lpa_started_at", table_name="live_publish_attempts")
    op.drop_index("ix_lpa_idempotency_key", table_name="live_publish_attempts")
    op.drop_index("ix_lpa_status", table_name="live_publish_attempts")
    op.drop_index("ix_lpa_mode", table_name="live_publish_attempts")
    op.drop_index("ix_lpa_trigger", table_name="live_publish_attempts")
    op.drop_index("ix_lpa_schedule_run_id", table_name="live_publish_attempts")
    op.drop_index("ix_lpa_publication_id", table_name="live_publish_attempts")
    op.drop_index("ix_lpa_post_id", table_name="live_publish_attempts")
    op.drop_index("ix_lpa_platform_key", table_name="live_publish_attempts")
    op.drop_index("ix_lpa_project_id", table_name="live_publish_attempts")
    op.drop_index("ix_lpa_account_id", table_name="live_publish_attempts")
    op.drop_table("live_publish_attempts")
