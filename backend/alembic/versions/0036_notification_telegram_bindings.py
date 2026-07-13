"""Notification Telegram bindings (v0.5.4)

Revision ID: 0036_telegram_bindings
Revises: 0035_email_templates
Create Date: 2026-07-13

Foundation привязки Telegram как канала уведомлений. chat_id / telegram_user_id хранятся
encrypted + masked + sha256-hash; verification token — hash + prefix. Реальной Telegram-доставки
нет (sandbox по умолчанию); bot token в БД не хранится. Совместимо со SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0036_telegram_bindings"
down_revision: str | None = "0035_email_templates"
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
        "notification_telegram_bindings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="draft"),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("telegram_user_id_encrypted", sa.Text(), nullable=True),
        sa.Column("telegram_user_id_masked", sa.String(length=64), nullable=True),
        sa.Column("telegram_user_id_hash", sa.String(length=64), nullable=True),
        sa.Column("chat_id_encrypted", sa.Text(), nullable=True),
        sa.Column("chat_id_masked", sa.String(length=64), nullable=True),
        sa.Column("chat_id_hash", sa.String(length=64), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("verification_token_hash", sa.String(length=64), nullable=True),
        sa.Column("verification_token_prefix", sa.String(length=16), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=512), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("binding_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ntb_user_id", "notification_telegram_bindings", ["user_id"])
    op.create_index("ix_ntb_account_id", "notification_telegram_bindings", ["account_id"])
    op.create_index("ix_ntb_project_id", "notification_telegram_bindings", ["project_id"])
    op.create_index("ix_ntb_status", "notification_telegram_bindings", ["status"])
    op.create_index(
        "ix_ntb_telegram_user_id_hash", "notification_telegram_bindings", ["telegram_user_id_hash"]
    )
    op.create_index("ix_ntb_chat_id_hash", "notification_telegram_bindings", ["chat_id_hash"])
    op.create_index(
        "ix_ntb_verification_token_hash",
        "notification_telegram_bindings",
        ["verification_token_hash"],
    )
    op.create_index("ix_ntb_created_at", "notification_telegram_bindings", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_ntb_created_at", table_name="notification_telegram_bindings")
    op.drop_index("ix_ntb_verification_token_hash", table_name="notification_telegram_bindings")
    op.drop_index("ix_ntb_chat_id_hash", table_name="notification_telegram_bindings")
    op.drop_index("ix_ntb_telegram_user_id_hash", table_name="notification_telegram_bindings")
    op.drop_index("ix_ntb_status", table_name="notification_telegram_bindings")
    op.drop_index("ix_ntb_project_id", table_name="notification_telegram_bindings")
    op.drop_index("ix_ntb_account_id", table_name="notification_telegram_bindings")
    op.drop_index("ix_ntb_user_id", table_name="notification_telegram_bindings")
    op.drop_table("notification_telegram_bindings")
