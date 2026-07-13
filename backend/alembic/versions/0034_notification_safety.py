"""Notification safety: opt-outs, suppressions, rate limits, webhook subscriptions (v0.5.2)

Revision ID: 0034_notification_safety
Revises: 0033_notification_delivery
Create Date: 2026-07-13

Safety-слой перед реальной внешней доставкой: отписки (opt-out), подавление (suppression),
rate-limit бакеты и подписки на webhook (URL/secret хранятся encrypted + masked). Реальной
внешней доставки нет; без сырых секретов/адресов. Совместимо со SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0034_notification_safety"
down_revision: str | None = "0033_notification_delivery"
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
    # --- Отписки (opt-out) --- #
    op.create_table(
        "notification_opt_outs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("channel", sa.String(length=20), nullable=True),
        sa.Column("notification_type", sa.String(length=40), nullable=True),
        sa.Column("scope", sa.String(length=30), nullable=False, server_default="global"),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("revoked_by_user_id", sa.Integer(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opt_out_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revoked_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_noo_user_id", "notification_opt_outs", ["user_id"])
    op.create_index("ix_noo_account_id", "notification_opt_outs", ["account_id"])
    op.create_index("ix_noo_project_id", "notification_opt_outs", ["project_id"])
    op.create_index("ix_noo_channel", "notification_opt_outs", ["channel"])
    op.create_index("ix_noo_type", "notification_opt_outs", ["notification_type"])
    op.create_index("ix_noo_scope", "notification_opt_outs", ["scope"])
    op.create_index("ix_noo_status", "notification_opt_outs", ["status"])

    # --- Подавление (suppression) --- #
    op.create_table(
        "notification_suppressions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("channel", sa.String(length=20), nullable=False, server_default="email"),
        sa.Column("provider", sa.String(length=20), nullable=True),
        sa.Column("destination_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "reason", sa.String(length=40), nullable=False, server_default="too_many_failures"
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suppressed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleared_by_user_id", sa.Integer(), nullable=True),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suppression_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cleared_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_nsup_account_id", "notification_suppressions", ["account_id"])
    op.create_index("ix_nsup_project_id", "notification_suppressions", ["project_id"])
    op.create_index("ix_nsup_user_id", "notification_suppressions", ["user_id"])
    op.create_index("ix_nsup_channel", "notification_suppressions", ["channel"])
    op.create_index("ix_nsup_provider", "notification_suppressions", ["provider"])
    op.create_index("ix_nsup_status", "notification_suppressions", ["status"])
    op.create_index("ix_nsup_until", "notification_suppressions", ["suppressed_until"])

    # --- Rate-limit бакеты --- #
    op.create_table(
        "notification_rate_limit_buckets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("channel", sa.String(length=20), nullable=True),
        sa.Column("provider", sa.String(length=20), nullable=True),
        sa.Column("notification_type", sa.String(length=40), nullable=True),
        sa.Column("scope", sa.String(length=30), nullable=False, server_default="user"),
        sa.Column("bucket_key", sa.String(length=255), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False, server_default="3600"),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("limit_value", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("reset_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bucket_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_nrl_bucket_key", "notification_rate_limit_buckets", ["bucket_key"])
    op.create_index("ix_nrl_window_start", "notification_rate_limit_buckets", ["window_start"])
    op.create_index("ix_nrl_reset_at", "notification_rate_limit_buckets", ["reset_at"])
    op.create_index("ix_nrl_account_id", "notification_rate_limit_buckets", ["account_id"])
    op.create_index("ix_nrl_project_id", "notification_rate_limit_buckets", ["project_id"])
    op.create_index("ix_nrl_user_id", "notification_rate_limit_buckets", ["user_id"])

    # --- Webhook-подписки --- #
    op.create_table(
        "webhook_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("url_masked", sa.String(length=255), nullable=True),
        sa.Column("url_hash", sa.String(length=64), nullable=True),
        sa.Column("url_encrypted", sa.Text(), nullable=True),
        sa.Column("signing_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("signing_secret_masked", sa.String(length=64), nullable=True),
        sa.Column(
            "signature_algorithm",
            sa.String(length=20),
            nullable=False,
            server_default="hmac_sha256",
        ),
        sa.Column("event_types", _json(), nullable=False, server_default="[]"),
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=512), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("subscription_metadata", _json(), nullable=False, server_default="{}"),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_whs_account_id", "webhook_subscriptions", ["account_id"])
    op.create_index("ix_whs_project_id", "webhook_subscriptions", ["project_id"])
    op.create_index("ix_whs_user_id", "webhook_subscriptions", ["user_id"])
    op.create_index("ix_whs_status", "webhook_subscriptions", ["status"])
    op.create_index("ix_whs_url_hash", "webhook_subscriptions", ["url_hash"])


def downgrade() -> None:
    op.drop_index("ix_whs_url_hash", table_name="webhook_subscriptions")
    op.drop_index("ix_whs_status", table_name="webhook_subscriptions")
    op.drop_index("ix_whs_user_id", table_name="webhook_subscriptions")
    op.drop_index("ix_whs_project_id", table_name="webhook_subscriptions")
    op.drop_index("ix_whs_account_id", table_name="webhook_subscriptions")
    op.drop_table("webhook_subscriptions")

    op.drop_index("ix_nrl_user_id", table_name="notification_rate_limit_buckets")
    op.drop_index("ix_nrl_project_id", table_name="notification_rate_limit_buckets")
    op.drop_index("ix_nrl_account_id", table_name="notification_rate_limit_buckets")
    op.drop_index("ix_nrl_reset_at", table_name="notification_rate_limit_buckets")
    op.drop_index("ix_nrl_window_start", table_name="notification_rate_limit_buckets")
    op.drop_index("ix_nrl_bucket_key", table_name="notification_rate_limit_buckets")
    op.drop_table("notification_rate_limit_buckets")

    op.drop_index("ix_nsup_until", table_name="notification_suppressions")
    op.drop_index("ix_nsup_status", table_name="notification_suppressions")
    op.drop_index("ix_nsup_provider", table_name="notification_suppressions")
    op.drop_index("ix_nsup_channel", table_name="notification_suppressions")
    op.drop_index("ix_nsup_user_id", table_name="notification_suppressions")
    op.drop_index("ix_nsup_project_id", table_name="notification_suppressions")
    op.drop_index("ix_nsup_account_id", table_name="notification_suppressions")
    op.drop_table("notification_suppressions")

    op.drop_index("ix_noo_status", table_name="notification_opt_outs")
    op.drop_index("ix_noo_scope", table_name="notification_opt_outs")
    op.drop_index("ix_noo_type", table_name="notification_opt_outs")
    op.drop_index("ix_noo_channel", table_name="notification_opt_outs")
    op.drop_index("ix_noo_project_id", table_name="notification_opt_outs")
    op.drop_index("ix_noo_account_id", table_name="notification_opt_outs")
    op.drop_index("ix_noo_user_id", table_name="notification_opt_outs")
    op.drop_table("notification_opt_outs")
