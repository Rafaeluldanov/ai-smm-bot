"""Schedule media decisions (auto media selection) (v0.4.5)

Revision ID: 0027_schedule_media_decisions
Revises: 0026_schedule_topic_decisions
Create Date: 2026-07-12

Решение о media strategy и конкретных медиа для слота расписания — «почему бот выбрал эти
медиа». Пост создаётся только как draft/needs_review; live-публикаций нет; публичные ссылки
автоматически не создаются; секретов и внутренних путей в payload нет. Совместимо со SQLite
и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0027_schedule_media_decisions"
down_revision: str | None = "0026_schedule_topic_decisions"
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
        "schedule_media_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("platform_key", sa.String(length=40), nullable=True),
        sa.Column("publishing_plan_id", sa.Integer(), nullable=True),
        sa.Column("schedule_run_id", sa.Integer(), nullable=True),
        sa.Column("schedule_topic_decision_id", sa.Integer(), nullable=True),
        sa.Column(
            "selected_strategy", sa.String(length=32), nullable=False, server_default="text_only"
        ),
        sa.Column("selected_media_asset_ids", _json(), nullable=False, server_default="[]"),
        sa.Column("selected_media_variant_ids", _json(), nullable=False, server_default="[]"),
        sa.Column("selected_media_tags", _json(), nullable=False, server_default="[]"),
        sa.Column("selected_media_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "needs_public_image_url", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("media_proxy_ready", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("public_link_ids", _json(), nullable=False, server_default="[]"),
        sa.Column(
            "decision_source", sa.String(length=40), nullable=False, server_default="fallback"
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="preview"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("expected_media_score", sa.Integer(), nullable=True),
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
            ["schedule_topic_decision_id"], ["schedule_topic_decisions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_schedule_media_decisions_idempotency_key",
        "schedule_media_decisions",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_schedule_media_decisions_account_id", "schedule_media_decisions", ["account_id"]
    )
    op.create_index(
        "ix_schedule_media_decisions_project_id", "schedule_media_decisions", ["project_id"]
    )
    op.create_index(
        "ix_schedule_media_decisions_platform_key", "schedule_media_decisions", ["platform_key"]
    )
    op.create_index(
        "ix_schedule_media_decisions_schedule_run_id",
        "schedule_media_decisions",
        ["schedule_run_id"],
    )
    op.create_index(
        "ix_schedule_media_decisions_topic_decision_id",
        "schedule_media_decisions",
        ["schedule_topic_decision_id"],
    )
    op.create_index("ix_schedule_media_decisions_status", "schedule_media_decisions", ["status"])
    op.create_index(
        "ix_schedule_media_decisions_selected_strategy",
        "schedule_media_decisions",
        ["selected_strategy"],
    )
    op.create_index(
        "ix_schedule_media_decisions_created_at", "schedule_media_decisions", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_schedule_media_decisions_created_at", table_name="schedule_media_decisions")
    op.drop_index(
        "ix_schedule_media_decisions_selected_strategy", table_name="schedule_media_decisions"
    )
    op.drop_index("ix_schedule_media_decisions_status", table_name="schedule_media_decisions")
    op.drop_index(
        "ix_schedule_media_decisions_topic_decision_id", table_name="schedule_media_decisions"
    )
    op.drop_index(
        "ix_schedule_media_decisions_schedule_run_id", table_name="schedule_media_decisions"
    )
    op.drop_index("ix_schedule_media_decisions_platform_key", table_name="schedule_media_decisions")
    op.drop_index("ix_schedule_media_decisions_project_id", table_name="schedule_media_decisions")
    op.drop_index("ix_schedule_media_decisions_account_id", table_name="schedule_media_decisions")
    op.drop_index(
        "ix_schedule_media_decisions_idempotency_key", table_name="schedule_media_decisions"
    )
    op.drop_table("schedule_media_decisions")
