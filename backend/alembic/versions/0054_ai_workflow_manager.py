"""AI Workflow Manager: business workflows + steps + blockers (v0.7.2)

Revision ID: 0054_ai_workflow_manager
Revises: 0053_ai_chief_of_staff
Create Date: 2026-07-15

Слой управления процессами (Business Execution Layer): бизнес-процессы + этапы + блокеры
(Create → Steps → Assign → Track → Analyze → Recommend). Секретов не хранит; НЕ выполняет
задачи, НЕ меняет CRM/бюджет/продажи/live/публикации. Совместимо со SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0054_ai_workflow_manager"
down_revision: str | None = "0053_ai_chief_of_staff"
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
        "business_workflows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("workflow_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column("target_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("current_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("progress_percent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("workflow_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_business_workflows_account_id", "business_workflows", ["account_id"])
    op.create_index("ix_business_workflows_project_id", "business_workflows", ["project_id"])
    op.create_index("ix_business_workflows_account", "business_workflows", ["account_id"])
    op.create_index(
        "ix_business_workflows_project_status", "business_workflows", ["project_id", "status"]
    )

    op.create_table(
        "workflow_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("order_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("progress_percent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("step_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workflow_id"], ["business_workflows.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workflow_steps_workflow_id", "workflow_steps", ["workflow_id"])
    op.create_index(
        "ix_workflow_steps_workflow_order", "workflow_steps", ["workflow_id", "order_number"]
    )
    op.create_index(
        "ix_workflow_steps_workflow_status", "workflow_steps", ["workflow_id", "status"]
    )

    op.create_table(
        "workflow_blockers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("step_id", sa.Integer(), nullable=True),
        sa.Column("blocker_type", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workflow_id"], ["business_workflows.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["step_id"], ["workflow_steps.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workflow_blockers_workflow_id", "workflow_blockers", ["workflow_id"])
    op.create_index(
        "ix_workflow_blockers_workflow_status", "workflow_blockers", ["workflow_id", "status"]
    )
    op.create_index("ix_workflow_blockers_step", "workflow_blockers", ["step_id"])


def downgrade() -> None:
    op.drop_index("ix_workflow_blockers_step", table_name="workflow_blockers")
    op.drop_index("ix_workflow_blockers_workflow_status", table_name="workflow_blockers")
    op.drop_index("ix_workflow_blockers_workflow_id", table_name="workflow_blockers")
    op.drop_table("workflow_blockers")

    op.drop_index("ix_workflow_steps_workflow_status", table_name="workflow_steps")
    op.drop_index("ix_workflow_steps_workflow_order", table_name="workflow_steps")
    op.drop_index("ix_workflow_steps_workflow_id", table_name="workflow_steps")
    op.drop_table("workflow_steps")

    op.drop_index("ix_business_workflows_project_status", table_name="business_workflows")
    op.drop_index("ix_business_workflows_account", table_name="business_workflows")
    op.drop_index("ix_business_workflows_project_id", table_name="business_workflows")
    op.drop_index("ix_business_workflows_account_id", table_name="business_workflows")
    op.drop_table("business_workflows")
