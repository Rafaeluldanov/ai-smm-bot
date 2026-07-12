"""Notifications, mentions and preferences (v0.5.0)

Revision ID: 0032_notifications_mentions
Revises: 0031_media_curation_review
Create Date: 2026-07-12

Внутренние (in-app) уведомления, упоминания (@mentions) и настройки уведомлений. Внешней
доставки (email/webhook/push) нет; live-публикаций/платежей не подразумевает; без секретов/
внутренних путей. Совместимо со SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0032_notifications_mentions"
down_revision: str | None = "0031_media_curation_review"
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
    # --- Внутренние уведомления --- #
    op.create_table(
        "app_notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("recipient_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "notification_type",
            sa.String(length=40),
            nullable=False,
            server_default="system_notice",
        ),
        sa.Column("channel", sa.String(length=20), nullable=False, server_default="in_app"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="unread"),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="normal"),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("entity_type", sa.String(length=40), nullable=True),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("action_url", sa.String(length=512), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_delivery_error", sa.String(length=512), nullable=True),
        sa.Column("notification_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_app_notifications_account_id", "app_notifications", ["account_id"])
    op.create_index("ix_app_notifications_project_id", "app_notifications", ["project_id"])
    op.create_index("ix_app_notifications_recipient", "app_notifications", ["recipient_user_id"])
    op.create_index("ix_app_notifications_status", "app_notifications", ["status"])
    op.create_index("ix_app_notifications_type", "app_notifications", ["notification_type"])
    op.create_index("ix_app_notifications_priority", "app_notifications", ["priority"])
    op.create_index("ix_app_notifications_due_at", "app_notifications", ["due_at"])
    op.create_index("ix_app_notifications_created_at", "app_notifications", ["created_at"])
    op.create_index("ix_app_notifications_entity_type", "app_notifications", ["entity_type"])
    op.create_index("ix_app_notifications_entity_id", "app_notifications", ["entity_id"])
    op.create_index(
        "ix_app_notifications_entity", "app_notifications", ["entity_type", "entity_id"]
    )

    # --- Упоминания (@mentions) --- #
    op.create_table(
        "app_mentions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("source_entity_type", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("source_entity_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("comment_id", sa.Integer(), nullable=True),
        sa.Column("mentioned_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("mentioned_user_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="unresolved"),
        sa.Column("notification_id", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mention_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["mentioned_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["notification_id"], ["app_notifications.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_app_mentions_account_id", "app_mentions", ["account_id"])
    op.create_index("ix_app_mentions_project_id", "app_mentions", ["project_id"])
    op.create_index("ix_app_mentions_mentioned_user", "app_mentions", ["mentioned_user_id"])
    op.create_index("ix_app_mentions_status", "app_mentions", ["status"])
    op.create_index("ix_app_mentions_created_at", "app_mentions", ["created_at"])
    op.create_index(
        "ix_app_mentions_source", "app_mentions", ["source_entity_type", "source_entity_id"]
    )

    # --- Настройки уведомлений --- #
    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("channel", sa.String(length=20), nullable=False, server_default="in_app"),
        sa.Column("notification_type", sa.String(length=40), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("digest_frequency", sa.String(length=20), nullable=True),
        sa.Column("quiet_hours", _json(), nullable=False, server_default="{}"),
        sa.Column("preference_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notification_preferences_user_id", "notification_preferences", ["user_id"])
    op.create_index(
        "ix_notification_preferences_account_id", "notification_preferences", ["account_id"]
    )
    op.create_index("ix_notification_preferences_channel", "notification_preferences", ["channel"])
    op.create_index(
        "ix_notification_preferences_type", "notification_preferences", ["notification_type"]
    )


def downgrade() -> None:
    op.drop_index("ix_notification_preferences_type", table_name="notification_preferences")
    op.drop_index("ix_notification_preferences_channel", table_name="notification_preferences")
    op.drop_index("ix_notification_preferences_account_id", table_name="notification_preferences")
    op.drop_index("ix_notification_preferences_user_id", table_name="notification_preferences")
    op.drop_table("notification_preferences")

    op.drop_index("ix_app_mentions_source", table_name="app_mentions")
    op.drop_index("ix_app_mentions_created_at", table_name="app_mentions")
    op.drop_index("ix_app_mentions_status", table_name="app_mentions")
    op.drop_index("ix_app_mentions_mentioned_user", table_name="app_mentions")
    op.drop_index("ix_app_mentions_project_id", table_name="app_mentions")
    op.drop_index("ix_app_mentions_account_id", table_name="app_mentions")
    op.drop_table("app_mentions")

    op.drop_index("ix_app_notifications_entity", table_name="app_notifications")
    op.drop_index("ix_app_notifications_entity_id", table_name="app_notifications")
    op.drop_index("ix_app_notifications_entity_type", table_name="app_notifications")
    op.drop_index("ix_app_notifications_created_at", table_name="app_notifications")
    op.drop_index("ix_app_notifications_due_at", table_name="app_notifications")
    op.drop_index("ix_app_notifications_priority", table_name="app_notifications")
    op.drop_index("ix_app_notifications_type", table_name="app_notifications")
    op.drop_index("ix_app_notifications_status", table_name="app_notifications")
    op.drop_index("ix_app_notifications_recipient", table_name="app_notifications")
    op.drop_index("ix_app_notifications_project_id", table_name="app_notifications")
    op.drop_index("ix_app_notifications_account_id", table_name="app_notifications")
    op.drop_table("app_notifications")
