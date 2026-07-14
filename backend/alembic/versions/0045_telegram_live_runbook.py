"""Telegram live runbook: runbooks + run attempts (v0.6.3)

Revision ID: 0045_telegram_live_runbook
Revises: 0044_media_proxy_layer
Create Date: 2026-07-14

Первый production Telegram-канал: runbook готовности + журнал production-тестов. Секретов/сырых
токенов/payload не хранит; глобальные live-флаги не трогает. Совместимо со SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0045_telegram_live_runbook"
down_revision: str | None = "0044_media_proxy_layer"
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
        "telegram_live_runbooks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("channel_id", sa.String(length=128), nullable=True),
        sa.Column("channel_name", sa.String(length=255), nullable=True),
        sa.Column("connected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "media_proxy_ready", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("calendar_ready", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("readiness_ready", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "monitoring_ready", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("balance_ready", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checklist", _json(), nullable=False, server_default="{}"),
        sa.Column("blockers", _json(), nullable=False, server_default="[]"),
        sa.Column("warnings", _json(), nullable=False, server_default="[]"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tlr_account_id", "telegram_live_runbooks", ["account_id"])
    op.create_index("ix_tlr_project_id", "telegram_live_runbooks", ["project_id"])
    op.create_index("ix_tlr_status", "telegram_live_runbooks", ["status"])

    op.create_table(
        "telegram_live_run_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("runbook_id", sa.Integer(), nullable=True),
        sa.Column("post_id", sa.Integer(), nullable=True),
        sa.Column("publication_id", sa.Integer(), nullable=True),
        sa.Column("live_publish_attempt_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="preview"),
        sa.Column("confirmation_text", sa.String(length=64), nullable=True),
        sa.Column("payload_preview", _json(), nullable=False, server_default="{}"),
        sa.Column("external_post_id", sa.String(length=255), nullable=True),
        sa.Column("external_url", sa.String(length=1024), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["runbook_id"], ["telegram_live_runbooks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tlra_account_id", "telegram_live_run_attempts", ["account_id"])
    op.create_index("ix_tlra_project_id", "telegram_live_run_attempts", ["project_id"])
    op.create_index("ix_tlra_runbook_id", "telegram_live_run_attempts", ["runbook_id"])
    op.create_index("ix_tlra_post_id", "telegram_live_run_attempts", ["post_id"])
    op.create_index("ix_tlra_status", "telegram_live_run_attempts", ["status"])
    op.create_index(
        "ix_tlra_live_publish_attempt_id",
        "telegram_live_run_attempts",
        ["live_publish_attempt_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_tlra_live_publish_attempt_id", table_name="telegram_live_run_attempts")
    op.drop_index("ix_tlra_status", table_name="telegram_live_run_attempts")
    op.drop_index("ix_tlra_post_id", table_name="telegram_live_run_attempts")
    op.drop_index("ix_tlra_runbook_id", table_name="telegram_live_run_attempts")
    op.drop_index("ix_tlra_project_id", table_name="telegram_live_run_attempts")
    op.drop_index("ix_tlra_account_id", table_name="telegram_live_run_attempts")
    op.drop_table("telegram_live_run_attempts")

    op.drop_index("ix_tlr_status", table_name="telegram_live_runbooks")
    op.drop_index("ix_tlr_project_id", table_name="telegram_live_runbooks")
    op.drop_index("ix_tlr_account_id", table_name="telegram_live_runbooks")
    op.drop_table("telegram_live_runbooks")
