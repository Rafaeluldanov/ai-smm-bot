"""Metric import runs (v0.4.1)

Revision ID: 0023_metric_import_runs
Revises: 0022_automation_modes_learning
Create Date: 2026-07-11

Импорт метрик постов и обратная связь обучения: прогоны импорта метрик из источников
(demo / manual / estimated / internal / api). Реальные внешние API по умолчанию
выключены. Секретов в ``import_metadata`` нет. Совместимо со SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0023_metric_import_runs"
down_revision: str | None = "0022_automation_modes_learning"
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
        "metric_import_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("platform_key", sa.String(length=40), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("period_start", sa.String(length=20), nullable=True),
        sa.Column("period_end", sa.String(length=20), nullable=True),
        sa.Column("publications_scanned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metrics_imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("snapshots_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("learning_events_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("units_estimated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("units_charged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("import_metadata", _json(), nullable=False, server_default="{}"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_metric_import_runs_idempotency_key",
        "metric_import_runs",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index("ix_metric_import_runs_account_id", "metric_import_runs", ["account_id"])
    op.create_index("ix_metric_import_runs_project_id", "metric_import_runs", ["project_id"])
    op.create_index("ix_metric_import_runs_platform_key", "metric_import_runs", ["platform_key"])
    op.create_index("ix_metric_import_runs_source", "metric_import_runs", ["source"])
    op.create_index("ix_metric_import_runs_status", "metric_import_runs", ["status"])
    op.create_index("ix_metric_import_runs_created_at", "metric_import_runs", ["created_at"])
    op.create_index(
        "ix_metric_import_runs_created_by_user_id",
        "metric_import_runs",
        ["created_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_metric_import_runs_created_by_user_id", table_name="metric_import_runs")
    op.drop_index("ix_metric_import_runs_created_at", table_name="metric_import_runs")
    op.drop_index("ix_metric_import_runs_status", table_name="metric_import_runs")
    op.drop_index("ix_metric_import_runs_source", table_name="metric_import_runs")
    op.drop_index("ix_metric_import_runs_platform_key", table_name="metric_import_runs")
    op.drop_index("ix_metric_import_runs_project_id", table_name="metric_import_runs")
    op.drop_index("ix_metric_import_runs_account_id", table_name="metric_import_runs")
    op.drop_index("ix_metric_import_runs_idempotency_key", table_name="metric_import_runs")
    op.drop_table("metric_import_runs")
