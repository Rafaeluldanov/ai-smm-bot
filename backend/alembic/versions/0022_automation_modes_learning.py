"""Automation modes + client learning (v0.4.0)

Revision ID: 0022_automation_modes_learning
Revises: 0021_scheduler_worker_leases
Create Date: 2026-07-11

Полу-/полностью автоматический режим публикаций и обучение бота на клиенте:
- новые таблицы ``client_learning_profiles`` (персональный профиль обучения) и
  ``post_feedback_events`` (сигналы: одобрение/правка/отклонение/аналитика);
- поля режима автоматизации в ``crm_publishing_plans``;
- поля попытки авто-публикации/качества/версии профиля в ``schedule_runs``.

Секретов нигде нет. Совместимо со SQLite (тесты) и PostgreSQL (JSONB variant).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0022_automation_modes_learning"
down_revision: str | None = "0021_scheduler_worker_leases"
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
    # --- client_learning_profiles ---
    op.create_table(
        "client_learning_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("platform_key", sa.String(length=40), nullable=True),
        sa.Column("profile_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("brand_voice", _json(), nullable=False, server_default="{}"),
        sa.Column("preferred_topics", _json(), nullable=False, server_default="[]"),
        sa.Column("rejected_topics", _json(), nullable=False, server_default="[]"),
        sa.Column("preferred_cta", _json(), nullable=False, server_default="[]"),
        sa.Column("rejected_cta", _json(), nullable=False, server_default="[]"),
        sa.Column("preferred_text_length", _json(), nullable=False, server_default="{}"),
        sa.Column("preferred_media_types", _json(), nullable=False, server_default="[]"),
        sa.Column("high_performing_tags", _json(), nullable=False, server_default="[]"),
        sa.Column("low_performing_tags", _json(), nullable=False, server_default="[]"),
        sa.Column("best_publish_times", _json(), nullable=False, server_default="[]"),
        sa.Column("approval_patterns", _json(), nullable=False, server_default="{}"),
        sa.Column("editing_patterns", _json(), nullable=False, server_default="{}"),
        sa.Column("performance_patterns", _json(), nullable=False, server_default="{}"),
        sa.Column("forbidden_patterns", _json(), nullable=False, server_default="[]"),
        sa.Column("recommendations", _json(), nullable=False, server_default="[]"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("updated_from_events_count", sa.Integer(), nullable=False, server_default="0"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_client_learning_profiles_account_id", "client_learning_profiles", ["account_id"]
    )
    op.create_index(
        "ix_client_learning_profiles_project_id", "client_learning_profiles", ["project_id"]
    )
    op.create_index("ix_client_learning_profiles_status", "client_learning_profiles", ["status"])
    op.create_index(
        "ix_client_learning_profiles_project_platform",
        "client_learning_profiles",
        ["project_id", "platform_key"],
    )

    # --- post_feedback_events ---
    op.create_table(
        "post_feedback_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("publication_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("platform_key", sa.String(length=40), nullable=True),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("reason_tags", _json(), nullable=False, server_default="[]"),
        sa.Column("before_text_hash", sa.String(length=64), nullable=True),
        sa.Column("after_text_hash", sa.String(length=64), nullable=True),
        sa.Column("diff_summary", _json(), nullable=False, server_default="{}"),
        sa.Column("metrics_snapshot", _json(), nullable=False, server_default="{}"),
        sa.Column("event_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["publication_id"], ["post_publications.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_post_feedback_events_account_id", "post_feedback_events", ["account_id"])
    op.create_index("ix_post_feedback_events_project_id", "post_feedback_events", ["project_id"])
    op.create_index("ix_post_feedback_events_post_id", "post_feedback_events", ["post_id"])
    op.create_index(
        "ix_post_feedback_events_publication_id", "post_feedback_events", ["publication_id"]
    )
    op.create_index("ix_post_feedback_events_user_id", "post_feedback_events", ["user_id"])
    op.create_index("ix_post_feedback_events_event_type", "post_feedback_events", ["event_type"])
    op.create_index(
        "ix_post_feedback_events_project_platform",
        "post_feedback_events",
        ["project_id", "platform_key"],
    )
    op.create_index("ix_post_feedback_events_created_at", "post_feedback_events", ["created_at"])

    # --- crm_publishing_plans: поля режима автоматизации ---
    op.add_column(
        "crm_publishing_plans",
        sa.Column(
            "automation_mode", sa.String(length=20), nullable=False, server_default="semi_auto"
        ),
    )
    op.add_column(
        "crm_publishing_plans",
        sa.Column("auto_publish_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "crm_publishing_plans",
        sa.Column("learning_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "crm_publishing_plans",
        sa.Column(
            "require_review_before_first_auto",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "crm_publishing_plans",
        sa.Column("min_quality_score_for_auto", sa.Integer(), nullable=False, server_default="70"),
    )
    op.add_column(
        "crm_publishing_plans",
        sa.Column("max_posts_per_day_auto", sa.Integer(), nullable=True),
    )
    op.add_column(
        "crm_publishing_plans",
        sa.Column("safety_notes", _json(), nullable=False, server_default="[]"),
    )
    op.create_index(
        "ix_crm_publishing_plans_automation_mode",
        "crm_publishing_plans",
        ["automation_mode"],
    )

    # --- schedule_runs: поля попытки авто-публикации / качества / версии профиля ---
    op.add_column(
        "schedule_runs", sa.Column("automation_mode", sa.String(length=20), nullable=True)
    )
    op.add_column(
        "schedule_runs",
        sa.Column(
            "auto_publish_attempted", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "schedule_runs",
        sa.Column("auto_publish_blocked_reason", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "schedule_runs", sa.Column("learning_profile_version", sa.Integer(), nullable=True)
    )
    op.add_column("schedule_runs", sa.Column("quality_score", sa.Integer(), nullable=True))
    op.add_column("schedule_runs", sa.Column("safety_score", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("schedule_runs", "safety_score")
    op.drop_column("schedule_runs", "quality_score")
    op.drop_column("schedule_runs", "learning_profile_version")
    op.drop_column("schedule_runs", "auto_publish_blocked_reason")
    op.drop_column("schedule_runs", "auto_publish_attempted")
    op.drop_column("schedule_runs", "automation_mode")

    op.drop_index("ix_crm_publishing_plans_automation_mode", table_name="crm_publishing_plans")
    op.drop_column("crm_publishing_plans", "safety_notes")
    op.drop_column("crm_publishing_plans", "max_posts_per_day_auto")
    op.drop_column("crm_publishing_plans", "min_quality_score_for_auto")
    op.drop_column("crm_publishing_plans", "require_review_before_first_auto")
    op.drop_column("crm_publishing_plans", "learning_enabled")
    op.drop_column("crm_publishing_plans", "auto_publish_enabled")
    op.drop_column("crm_publishing_plans", "automation_mode")

    op.drop_index("ix_post_feedback_events_created_at", table_name="post_feedback_events")
    op.drop_index("ix_post_feedback_events_project_platform", table_name="post_feedback_events")
    op.drop_index("ix_post_feedback_events_event_type", table_name="post_feedback_events")
    op.drop_index("ix_post_feedback_events_user_id", table_name="post_feedback_events")
    op.drop_index("ix_post_feedback_events_publication_id", table_name="post_feedback_events")
    op.drop_index("ix_post_feedback_events_post_id", table_name="post_feedback_events")
    op.drop_index("ix_post_feedback_events_project_id", table_name="post_feedback_events")
    op.drop_index("ix_post_feedback_events_account_id", table_name="post_feedback_events")
    op.drop_table("post_feedback_events")

    op.drop_index(
        "ix_client_learning_profiles_project_platform", table_name="client_learning_profiles"
    )
    op.drop_index("ix_client_learning_profiles_status", table_name="client_learning_profiles")
    op.drop_index("ix_client_learning_profiles_project_id", table_name="client_learning_profiles")
    op.drop_index("ix_client_learning_profiles_account_id", table_name="client_learning_profiles")
    op.drop_table("client_learning_profiles")
