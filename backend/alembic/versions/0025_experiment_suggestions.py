"""Experiment suggestions (worker recommendations) (v0.4.3)

Revision ID: 0025_experiment_suggestions
Revises: 0024_content_experiments
Create Date: 2026-07-11

Предложения экспериментов/тем от worker-а (или клиента): что публиковать чаще, чего
избегать, что перетестировать. Live-публикаций нет; секретов в payload нет. Совместимо
со SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0025_experiment_suggestions"
down_revision: str | None = "0024_content_experiments"
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
        "experiment_suggestions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("platform_key", sa.String(length=40), nullable=True),
        sa.Column(
            "suggestion_type", sa.String(length=30), nullable=False, server_default="publish_more"
        ),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="worker"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="proposed"),
        sa.Column("topic", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("recommendation_payload", _json(), nullable=False, server_default="{}"),
        sa.Column("source_signals", _json(), nullable=False, server_default="[]"),
        sa.Column("risk_flags", _json(), nullable=False, server_default="[]"),
        sa.Column("suggested_cta", sa.String(length=512), nullable=True),
        sa.Column("suggested_media_type", sa.String(length=64), nullable=True),
        sa.Column("suggested_publish_time", sa.String(length=20), nullable=True),
        sa.Column("estimated_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("worker_owner_id", sa.String(length=128), nullable=True),
        sa.Column("schedule_run_id", sa.Integer(), nullable=True),
        sa.Column("experiment_id", sa.Integer(), nullable=True),
        sa.Column("accepted_by_user_id", sa.Integer(), nullable=True),
        sa.Column("rejected_by_user_id", sa.Integer(), nullable=True),
        sa.Column("dismissed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acted_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["schedule_run_id"], ["schedule_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["experiment_id"], ["content_experiments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["accepted_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["rejected_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["dismissed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_experiment_suggestions_idempotency_key",
        "experiment_suggestions",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_experiment_suggestions_account_id", "experiment_suggestions", ["account_id"]
    )
    op.create_index(
        "ix_experiment_suggestions_project_id", "experiment_suggestions", ["project_id"]
    )
    op.create_index(
        "ix_experiment_suggestions_platform_key", "experiment_suggestions", ["platform_key"]
    )
    op.create_index("ix_experiment_suggestions_status", "experiment_suggestions", ["status"])
    op.create_index(
        "ix_experiment_suggestions_suggestion_type",
        "experiment_suggestions",
        ["suggestion_type"],
    )
    op.create_index("ix_experiment_suggestions_source", "experiment_suggestions", ["source"])
    op.create_index(
        "ix_experiment_suggestions_experiment_id", "experiment_suggestions", ["experiment_id"]
    )
    op.create_index(
        "ix_experiment_suggestions_schedule_run_id",
        "experiment_suggestions",
        ["schedule_run_id"],
    )
    op.create_index(
        "ix_experiment_suggestions_created_at", "experiment_suggestions", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_experiment_suggestions_created_at", table_name="experiment_suggestions")
    op.drop_index("ix_experiment_suggestions_schedule_run_id", table_name="experiment_suggestions")
    op.drop_index("ix_experiment_suggestions_experiment_id", table_name="experiment_suggestions")
    op.drop_index("ix_experiment_suggestions_source", table_name="experiment_suggestions")
    op.drop_index("ix_experiment_suggestions_suggestion_type", table_name="experiment_suggestions")
    op.drop_index("ix_experiment_suggestions_status", table_name="experiment_suggestions")
    op.drop_index("ix_experiment_suggestions_platform_key", table_name="experiment_suggestions")
    op.drop_index("ix_experiment_suggestions_project_id", table_name="experiment_suggestions")
    op.drop_index("ix_experiment_suggestions_account_id", table_name="experiment_suggestions")
    op.drop_index("ix_experiment_suggestions_idempotency_key", table_name="experiment_suggestions")
    op.drop_table("experiment_suggestions")
