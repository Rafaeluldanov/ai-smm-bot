"""Notification Telegram update logs (v0.5.5)

Revision ID: 0037_telegram_updates
Revises: 0036_telegram_bindings
Create Date: 2026-07-13

История входящих Telegram-обновлений (webhook/polling sandbox). Сырые chat_id / telegram_user_id /
verification token / bot token НЕ хранятся (только hash + маска). Реальных Telegram API-вызовов нет.
Совместимо со SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0037_telegram_updates"
down_revision: str | None = "0036_telegram_bindings"
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
        "notification_telegram_update_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("binding_id", sa.Integer(), nullable=True),
        sa.Column("update_id", sa.Integer(), nullable=True),
        sa.Column("update_type", sa.String(length=24), nullable=False, server_default="unknown"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="received"),
        sa.Column("command", sa.String(length=24), nullable=True),
        sa.Column("chat_id_hash", sa.String(length=64), nullable=True),
        sa.Column("telegram_user_id_hash", sa.String(length=64), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("text_preview", sa.String(length=512), nullable=True),
        sa.Column("raw_update_sanitized", _json(), nullable=False, server_default="{}"),
        sa.Column("result_metadata", _json(), nullable=False, server_default="{}"),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["binding_id"], ["notification_telegram_bindings.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ntul_update_id", "notification_telegram_update_logs", ["update_id"])
    op.create_index("ix_ntul_status", "notification_telegram_update_logs", ["status"])
    op.create_index("ix_ntul_update_type", "notification_telegram_update_logs", ["update_type"])
    op.create_index("ix_ntul_command", "notification_telegram_update_logs", ["command"])
    op.create_index("ix_ntul_binding_id", "notification_telegram_update_logs", ["binding_id"])
    op.create_index("ix_ntul_user_id", "notification_telegram_update_logs", ["user_id"])
    op.create_index("ix_ntul_account_id", "notification_telegram_update_logs", ["account_id"])
    op.create_index("ix_ntul_project_id", "notification_telegram_update_logs", ["project_id"])
    op.create_index("ix_ntul_received_at", "notification_telegram_update_logs", ["received_at"])
    op.create_index("ix_ntul_chat_id_hash", "notification_telegram_update_logs", ["chat_id_hash"])
    op.create_index(
        "ix_ntul_telegram_user_id_hash",
        "notification_telegram_update_logs",
        ["telegram_user_id_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_ntul_telegram_user_id_hash", table_name="notification_telegram_update_logs")
    op.drop_index("ix_ntul_chat_id_hash", table_name="notification_telegram_update_logs")
    op.drop_index("ix_ntul_received_at", table_name="notification_telegram_update_logs")
    op.drop_index("ix_ntul_project_id", table_name="notification_telegram_update_logs")
    op.drop_index("ix_ntul_account_id", table_name="notification_telegram_update_logs")
    op.drop_index("ix_ntul_user_id", table_name="notification_telegram_update_logs")
    op.drop_index("ix_ntul_binding_id", table_name="notification_telegram_update_logs")
    op.drop_index("ix_ntul_command", table_name="notification_telegram_update_logs")
    op.drop_index("ix_ntul_update_type", table_name="notification_telegram_update_logs")
    op.drop_index("ix_ntul_status", table_name="notification_telegram_update_logs")
    op.drop_index("ix_ntul_update_id", table_name="notification_telegram_update_logs")
    op.drop_table("notification_telegram_update_logs")
