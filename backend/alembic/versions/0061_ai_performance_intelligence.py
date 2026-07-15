"""AI Performance Intelligence: snapshots + metrics + deviations + recommendations (v0.7.9)

Revision ID: 0061_ai_performance_intelligence
Revises: 0060_ai_execution_coordinator
Create Date: 2026-07-15

Аналитический слой (Performance Intelligence): измеряет эффективность исполнения бизнес-плана —
факт vs план, performance score, отклонения, причины, рекомендации. Execution Plan → Performance
Snapshot → Actual vs Target → Deviation Analysis → Recommendations. Секретов не хранит; НЕ меняет
планы/KPI/CRM/бюджет, НЕ выполняет задачи/рекомендации, НЕ запускает рекламу/публикации.
SQLite+PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic (<=32 chars: alembic_version.version_num is varchar(32)).
revision: str = "0061_ai_performance_intelligence"
down_revision: str | None = "0060_ai_execution_coordinator"
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


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "performance_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("execution_plan_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="healthy"),
        sa.Column("performance_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("metrics", _json(), nullable=False, server_default="{}"),
        sa.Column("target_state", _json(), nullable=False, server_default="{}"),
        sa.Column("actual_state", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["execution_plan_id"], ["execution_plans.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_performance_snapshots_account_id", "performance_snapshots", ["account_id"])
    op.create_index("ix_performance_snapshots_project_id", "performance_snapshots", ["project_id"])
    op.create_index(
        "ix_performance_snapshots_execution_plan_id",
        "performance_snapshots",
        ["execution_plan_id"],
    )
    op.create_index(
        "ix_performance_snapshots_project_status",
        "performance_snapshots",
        ["project_id", "status"],
    )

    op.create_table(
        "performance_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("metric", sa.String(length=20), nullable=False),
        sa.Column("target_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("actual_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("difference", sa.Float(), nullable=False, server_default="0"),
        sa.Column("difference_percent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="healthy"),
        sa.Column("reasoning", _json(), nullable=False, server_default="[]"),
        _created_at(),
        sa.ForeignKeyConstraint(["snapshot_id"], ["performance_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_performance_metrics_snapshot_id", "performance_metrics", ["snapshot_id"])

    op.create_table(
        "performance_deviations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column(
            "deviation_type", sa.String(length=20), nullable=False, server_default="negative"
        ),
        sa.Column("metric", sa.String(length=20), nullable=False),
        sa.Column("impact", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("root_causes", _json(), nullable=False, server_default="[]"),
        _created_at(),
        sa.ForeignKeyConstraint(["snapshot_id"], ["performance_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_performance_deviations_snapshot_id", "performance_deviations", ["snapshot_id"]
    )

    op.create_table(
        "performance_recommendations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("expected_effect", _json(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="generated"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["snapshot_id"], ["performance_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_performance_recommendations_snapshot_id",
        "performance_recommendations",
        ["snapshot_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_performance_recommendations_snapshot_id", table_name="performance_recommendations"
    )
    op.drop_table("performance_recommendations")

    op.drop_index("ix_performance_deviations_snapshot_id", table_name="performance_deviations")
    op.drop_table("performance_deviations")

    op.drop_index("ix_performance_metrics_snapshot_id", table_name="performance_metrics")
    op.drop_table("performance_metrics")

    op.drop_index("ix_performance_snapshots_project_status", table_name="performance_snapshots")
    op.drop_index("ix_performance_snapshots_execution_plan_id", table_name="performance_snapshots")
    op.drop_index("ix_performance_snapshots_project_id", table_name="performance_snapshots")
    op.drop_index("ix_performance_snapshots_account_id", table_name="performance_snapshots")
    op.drop_table("performance_snapshots")
