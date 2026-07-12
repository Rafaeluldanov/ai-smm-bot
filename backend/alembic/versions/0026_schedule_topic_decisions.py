"""Schedule topic decisions (auto topic selection) (v0.4.4)

Revision ID: 0026_schedule_topic_decisions
Revises: 0025_experiment_suggestions
Create Date: 2026-07-12

Решение о теме/CTA/формате/медиа-стратегии для слота расписания — «почему бот выбрал эту
тему». Пост создаётся только как draft/needs_review; live-публикаций нет; секретов в payload
нет. Совместимо со SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0026_schedule_topic_decisions"
down_revision: str | None = "0025_experiment_suggestions"
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
        "schedule_topic_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("platform_key", sa.String(length=40), nullable=True),
        sa.Column("publishing_plan_id", sa.Integer(), nullable=True),
        sa.Column("schedule_run_id", sa.Integer(), nullable=True),
        sa.Column("experiment_suggestion_id", sa.Integer(), nullable=True),
        sa.Column("content_experiment_id", sa.Integer(), nullable=True),
        sa.Column("selected_topic", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("selected_cta", sa.String(length=512), nullable=True),
        sa.Column("selected_format", sa.String(length=64), nullable=True),
        sa.Column("selected_media_strategy", sa.String(length=64), nullable=True),
        sa.Column("selected_publish_time", sa.String(length=20), nullable=True),
        sa.Column(
            "decision_source", sa.String(length=40), nullable=False, server_default="fallback"
        ),
        sa.Column("decision_mode", sa.String(length=20), nullable=False, server_default="dry_run"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="preview"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("expected_quality_score", sa.Integer(), nullable=True),
        sa.Column("expected_engagement_score", sa.Integer(), nullable=True),
        sa.Column("learning_profile_version", sa.Integer(), nullable=True),
        sa.Column("alternatives", _json(), nullable=False, server_default="[]"),
        sa.Column("source_signals", _json(), nullable=False, server_default="[]"),
        sa.Column("risk_flags", _json(), nullable=False, server_default="[]"),
        sa.Column("reasons", _json(), nullable=False, server_default="[]"),
        sa.Column("decision_metadata", _json(), nullable=False, server_default="{}"),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("created_by_worker_owner_id", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["publishing_plan_id"], ["crm_publishing_plans.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["schedule_run_id"], ["schedule_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["experiment_suggestion_id"], ["experiment_suggestions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["content_experiment_id"], ["content_experiments.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_schedule_topic_decisions_idempotency_key",
        "schedule_topic_decisions",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_schedule_topic_decisions_account_id", "schedule_topic_decisions", ["account_id"]
    )
    op.create_index(
        "ix_schedule_topic_decisions_project_id", "schedule_topic_decisions", ["project_id"]
    )
    op.create_index(
        "ix_schedule_topic_decisions_platform_key", "schedule_topic_decisions", ["platform_key"]
    )
    op.create_index(
        "ix_schedule_topic_decisions_publishing_plan_id",
        "schedule_topic_decisions",
        ["publishing_plan_id"],
    )
    op.create_index(
        "ix_schedule_topic_decisions_schedule_run_id",
        "schedule_topic_decisions",
        ["schedule_run_id"],
    )
    op.create_index("ix_schedule_topic_decisions_status", "schedule_topic_decisions", ["status"])
    op.create_index(
        "ix_schedule_topic_decisions_decision_source",
        "schedule_topic_decisions",
        ["decision_source"],
    )
    op.create_index(
        "ix_schedule_topic_decisions_created_at", "schedule_topic_decisions", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_schedule_topic_decisions_created_at", table_name="schedule_topic_decisions")
    op.drop_index(
        "ix_schedule_topic_decisions_decision_source", table_name="schedule_topic_decisions"
    )
    op.drop_index("ix_schedule_topic_decisions_status", table_name="schedule_topic_decisions")
    op.drop_index(
        "ix_schedule_topic_decisions_schedule_run_id", table_name="schedule_topic_decisions"
    )
    op.drop_index(
        "ix_schedule_topic_decisions_publishing_plan_id",
        table_name="schedule_topic_decisions",
    )
    op.drop_index("ix_schedule_topic_decisions_platform_key", table_name="schedule_topic_decisions")
    op.drop_index("ix_schedule_topic_decisions_project_id", table_name="schedule_topic_decisions")
    op.drop_index("ix_schedule_topic_decisions_account_id", table_name="schedule_topic_decisions")
    op.drop_index(
        "ix_schedule_topic_decisions_idempotency_key", table_name="schedule_topic_decisions"
    )
    op.drop_table("schedule_topic_decisions")
