"""AI Autonomous Optimization: optimization items + experiments + results (v0.8.1)

Revision ID: 0063_ai_autonomous_optimization
Revises: 0062_ai_continuous_improvement
Create Date: 2026-07-16

Optimization/аналитический слой: превращает Improvement Backlog в систему оценки, приоритизации и
проверки улучшений. Improvement Item → Optimization Score → Experiment → Measurement → Validation →
Learning Update. Секретов не хранит; НЕ применяет улучшения, НЕ меняет бизнес/KPI/CRM/бюджет, НЕ
выполняет задачи, НЕ запускает рекламу/публикации. SQLite+PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic (<=32 chars: alembic_version.version_num is varchar(32)).
revision: str = "0063_ai_autonomous_optimization"
down_revision: str | None = "0062_ai_continuous_improvement"
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
        "optimization_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("improvement_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("impact_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cost_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("risk_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("optimization_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="identified"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["improvement_id"], ["improvement_items.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_optimization_items_account_id", "optimization_items", ["account_id"])
    op.create_index("ix_optimization_items_project_id", "optimization_items", ["project_id"])
    op.create_index(
        "ix_optimization_items_improvement_id", "optimization_items", ["improvement_id"]
    )
    op.create_index(
        "ix_optimization_items_project_status", "optimization_items", ["project_id", "status"]
    )

    op.create_table(
        "optimization_experiments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("optimization_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=True),
        sa.Column("metric", sa.String(length=50), nullable=False, server_default=""),
        sa.Column("baseline_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("target_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("measurement_period", sa.Integer(), nullable=False, server_default="7"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["optimization_id"], ["optimization_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_optimization_experiments_optimization_id",
        "optimization_experiments",
        ["optimization_id"],
    )

    op.create_table(
        "experiment_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("experiment_id", sa.Integer(), nullable=False),
        sa.Column("actual_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("expected_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("difference", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "validation_result", sa.String(length=20), nullable=False, server_default="inconclusive"
        ),
        sa.Column("analysis", _json(), nullable=False, server_default="{}"),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["experiment_id"], ["optimization_experiments.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_experiment_results_experiment_id", "experiment_results", ["experiment_id"])


def downgrade() -> None:
    op.drop_index("ix_experiment_results_experiment_id", table_name="experiment_results")
    op.drop_table("experiment_results")

    op.drop_index(
        "ix_optimization_experiments_optimization_id", table_name="optimization_experiments"
    )
    op.drop_table("optimization_experiments")

    op.drop_index("ix_optimization_items_project_status", table_name="optimization_items")
    op.drop_index("ix_optimization_items_improvement_id", table_name="optimization_items")
    op.drop_index("ix_optimization_items_project_id", table_name="optimization_items")
    op.drop_index("ix_optimization_items_account_id", table_name="optimization_items")
    op.drop_table("optimization_items")
