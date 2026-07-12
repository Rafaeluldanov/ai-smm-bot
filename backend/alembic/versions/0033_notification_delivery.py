"""Notification delivery logs and digests (v0.5.1)

Revision ID: 0033_notification_delivery
Revises: 0032_notifications_mentions
Create Date: 2026-07-12

Журнал доставки уведомлений (email/telegram/webhook/digest) и дайджесты. В MVP реальной
внешней доставки нет (mock-провайдеры пишут лог, но ничего не отправляют); без секретов/
токенов/внутренних путей. Совместимо со SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0033_notification_delivery"
down_revision: str | None = "0032_notifications_mentions"
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
    # --- Журнал доставки уведомлений --- #
    op.create_table(
        "notification_delivery_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("notification_id", sa.Integer(), nullable=True),
        sa.Column("recipient_user_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=20), nullable=False, server_default="mock"),
        sa.Column("channel", sa.String(length=20), nullable=False, server_default="email"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("destination_masked", sa.String(length=255), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("message_preview", sa.Text(), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("request_metadata", _json(), nullable=False, server_default="{}"),
        sa.Column("response_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["notification_id"], ["app_notifications.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ndl_account_id", "notification_delivery_logs", ["account_id"])
    op.create_index("ix_ndl_project_id", "notification_delivery_logs", ["project_id"])
    op.create_index("ix_ndl_notification_id", "notification_delivery_logs", ["notification_id"])
    op.create_index("ix_ndl_recipient", "notification_delivery_logs", ["recipient_user_id"])
    op.create_index("ix_ndl_provider", "notification_delivery_logs", ["provider"])
    op.create_index("ix_ndl_channel", "notification_delivery_logs", ["channel"])
    op.create_index("ix_ndl_status", "notification_delivery_logs", ["status"])
    op.create_index("ix_ndl_next_retry_at", "notification_delivery_logs", ["next_retry_at"])
    op.create_index("ix_ndl_created_at", "notification_delivery_logs", ["created_at"])

    # --- Дайджесты уведомлений --- #
    op.create_table(
        "notification_digests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("frequency", sa.String(length=20), nullable=False, server_default="daily"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notification_ids", _json(), nullable=False, server_default="[]"),
        sa.Column("subject", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("body_preview", sa.Text(), nullable=True),
        sa.Column("body_metadata", _json(), nullable=False, server_default="{}"),
        sa.Column("delivery_log_id", sa.Integer(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["delivery_log_id"], ["notification_delivery_logs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ndigest_account_id", "notification_digests", ["account_id"])
    op.create_index("ix_ndigest_project_id", "notification_digests", ["project_id"])
    op.create_index("ix_ndigest_user_id", "notification_digests", ["user_id"])
    op.create_index("ix_ndigest_frequency", "notification_digests", ["frequency"])
    op.create_index("ix_ndigest_status", "notification_digests", ["status"])
    op.create_index("ix_ndigest_period_start", "notification_digests", ["period_start"])
    op.create_index("ix_ndigest_period_end", "notification_digests", ["period_end"])
    op.create_index("ix_ndigest_created_at", "notification_digests", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_ndigest_created_at", table_name="notification_digests")
    op.drop_index("ix_ndigest_period_end", table_name="notification_digests")
    op.drop_index("ix_ndigest_period_start", table_name="notification_digests")
    op.drop_index("ix_ndigest_status", table_name="notification_digests")
    op.drop_index("ix_ndigest_frequency", table_name="notification_digests")
    op.drop_index("ix_ndigest_user_id", table_name="notification_digests")
    op.drop_index("ix_ndigest_project_id", table_name="notification_digests")
    op.drop_index("ix_ndigest_account_id", table_name="notification_digests")
    op.drop_table("notification_digests")

    op.drop_index("ix_ndl_created_at", table_name="notification_delivery_logs")
    op.drop_index("ix_ndl_next_retry_at", table_name="notification_delivery_logs")
    op.drop_index("ix_ndl_status", table_name="notification_delivery_logs")
    op.drop_index("ix_ndl_channel", table_name="notification_delivery_logs")
    op.drop_index("ix_ndl_provider", table_name="notification_delivery_logs")
    op.drop_index("ix_ndl_recipient", table_name="notification_delivery_logs")
    op.drop_index("ix_ndl_notification_id", table_name="notification_delivery_logs")
    op.drop_index("ix_ndl_project_id", table_name="notification_delivery_logs")
    op.drop_index("ix_ndl_account_id", table_name="notification_delivery_logs")
    op.drop_table("notification_delivery_logs")
