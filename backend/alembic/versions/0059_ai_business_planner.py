"""AI Business Planner: goals + plans + objectives + milestones (v0.7.7)

Revision ID: 0059_ai_business_planner
Revises: 0058_ai_business_forecasting
Create Date: 2026-07-15

Planning-слой (Business Planner): превращает бизнес-цель в стратегический план через gap-анализ,
квартальные цели, KPI и roadmap. Business Goal → Gap Analysis → Strategic Plan → Quarter
Objectives → KPI → Milestones → Workflow Draft. Секретов не хранит; НЕ выполняет план, НЕ меняет
бизнес/CRM/бюджет, НЕ запускает рекламу/публикации; approve/convert меняют лишь статус / создают
ЧЕРНОВИК процесса. SQLite+PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic (<=32 chars: alembic_version.version_num is varchar(32)).
revision: str = "0059_ai_business_planner"
down_revision: str | None = "0058_ai_business_forecasting"
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
        "business_goals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("goal_type", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("target_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("current_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("target_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("goal_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_business_goals_account_id", "business_goals", ["account_id"])
    op.create_index("ix_business_goals_project_id", "business_goals", ["project_id"])
    op.create_index("ix_business_goals_project_status", "business_goals", ["project_id", "status"])

    op.create_table(
        "strategic_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("goal_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("gap_analysis", _json(), nullable=False, server_default="{}"),
        sa.Column("strategy", _json(), nullable=False, server_default="{}"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["goal_id"], ["business_goals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_strategic_plans_goal_id", "strategic_plans", ["goal_id"])

    op.create_table(
        "quarter_objectives",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("quarter", sa.String(length=10), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("kpi", _json(), nullable=False, server_default="[]"),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="planned"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["plan_id"], ["strategic_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quarter_objectives_plan_id", "quarter_objectives", ["plan_id"])

    op.create_table(
        "plan_milestones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("objective_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("target_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="planned"),
        sa.Column("milestone_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["objective_id"], ["quarter_objectives.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plan_milestones_objective_id", "plan_milestones", ["objective_id"])


def downgrade() -> None:
    op.drop_index("ix_plan_milestones_objective_id", table_name="plan_milestones")
    op.drop_table("plan_milestones")

    op.drop_index("ix_quarter_objectives_plan_id", table_name="quarter_objectives")
    op.drop_table("quarter_objectives")

    op.drop_index("ix_strategic_plans_goal_id", table_name="strategic_plans")
    op.drop_table("strategic_plans")

    op.drop_index("ix_business_goals_project_status", table_name="business_goals")
    op.drop_index("ix_business_goals_project_id", table_name="business_goals")
    op.drop_index("ix_business_goals_account_id", table_name="business_goals")
    op.drop_table("business_goals")
