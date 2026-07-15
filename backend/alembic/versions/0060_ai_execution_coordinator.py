"""AI Execution Coordinator: plans + objectives + tasks + dependencies (v0.7.8)

Revision ID: 0060_ai_execution_coordinator
Revises: 0059_ai_business_planner
Create Date: 2026-07-15

Coordination-слой (Execution Coordinator): превращает утверждённый стратегический план в
управляемую систему исполнения — цели, задачи, владельцы, сроки, прогресс, зависимости, блокеры.
Approved Strategic Plan → Execution Plan → Objectives → Tasks → Owners → Progress → AI
Coordination. Секретов не хранит; НЕ выполняет задачи, НЕ меняет бизнес/CRM/бюджет, НЕ запускает
рекламу/публикации; workflow-link создаёт лишь ЧЕРНОВИК процесса. SQLite+PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic (<=32 chars: alembic_version.version_num is varchar(32)).
revision: str = "0060_ai_execution_coordinator"
down_revision: str | None = "0059_ai_business_planner"
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
        "execution_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("strategic_plan_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("progress_percent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("plan_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["strategic_plan_id"], ["strategic_plans.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_execution_plans_account_id", "execution_plans", ["account_id"])
    op.create_index("ix_execution_plans_project_id", "execution_plans", ["project_id"])
    op.create_index(
        "ix_execution_plans_strategic_plan_id", "execution_plans", ["strategic_plan_id"]
    )
    op.create_index(
        "ix_execution_plans_project_status", "execution_plans", ["project_id", "status"]
    )

    op.create_table(
        "execution_objectives",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("execution_plan_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("kpi", _json(), nullable=False, server_default="[]"),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("progress_percent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["execution_plan_id"], ["execution_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_execution_objectives_execution_plan_id", "execution_objectives", ["execution_plan_id"]
    )
    op.create_index(
        "ix_execution_objectives_owner_user_id", "execution_objectives", ["owner_user_id"]
    )

    op.create_table(
        "execution_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("objective_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("progress_percent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("task_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["objective_id"], ["execution_objectives.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_execution_tasks_objective_id", "execution_tasks", ["objective_id"])
    op.create_index("ix_execution_tasks_owner_user_id", "execution_tasks", ["owner_user_id"])

    op.create_table(
        "execution_dependencies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("depends_on_task_id", sa.Integer(), nullable=True),
        sa.Column("dependency_type", sa.String(length=20), nullable=False, server_default="task"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["task_id"], ["execution_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_execution_dependencies_task_id", "execution_dependencies", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_execution_dependencies_task_id", table_name="execution_dependencies")
    op.drop_table("execution_dependencies")

    op.drop_index("ix_execution_tasks_owner_user_id", table_name="execution_tasks")
    op.drop_index("ix_execution_tasks_objective_id", table_name="execution_tasks")
    op.drop_table("execution_tasks")

    op.drop_index("ix_execution_objectives_owner_user_id", table_name="execution_objectives")
    op.drop_index("ix_execution_objectives_execution_plan_id", table_name="execution_objectives")
    op.drop_table("execution_objectives")

    op.drop_index("ix_execution_plans_project_status", table_name="execution_plans")
    op.drop_index("ix_execution_plans_strategic_plan_id", table_name="execution_plans")
    op.drop_index("ix_execution_plans_project_id", table_name="execution_plans")
    op.drop_index("ix_execution_plans_account_id", table_name="execution_plans")
    op.drop_table("execution_plans")
