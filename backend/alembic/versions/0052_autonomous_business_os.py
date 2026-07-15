"""Autonomous Business OS: objectives + executive plans + actions (v0.7.0)

Revision ID: 0052_autonomous_business_os
Revises: 0051_business_growth_agent
Create Date: 2026-07-15

Верхний уровень управления (AI Executive Layer): бизнес-цели + исполнительные планы +
бизнес-действия (Analyze → Recommend → Approve → Apply). Секретов не хранит; НЕ меняет
live/CRM/бюджет/публикации. Совместимо со SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0052_autonomous_business_os"
down_revision: str | None = "0051_business_growth_agent"
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
        "business_objectives",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("target_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("current_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unit", sa.String(length=40), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("objective_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_business_objectives_account_id", "business_objectives", ["account_id"])
    op.create_index("ix_business_objectives_project_id", "business_objectives", ["project_id"])
    op.create_index("ix_business_objectives_account", "business_objectives", ["account_id"])
    op.create_index(
        "ix_business_objectives_project_status", "business_objectives", ["project_id", "status"]
    )

    op.create_table(
        "ai_executive_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("objective_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("executive_summary", sa.Text(), nullable=True),
        sa.Column("current_state", _json(), nullable=False, server_default="{}"),
        sa.Column("priority_actions", _json(), nullable=False, server_default="[]"),
        sa.Column("risks", _json(), nullable=False, server_default="[]"),
        sa.Column("opportunities", _json(), nullable=False, server_default="[]"),
        sa.Column("expected_outcomes", _json(), nullable=False, server_default="{}"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["objective_id"], ["business_objectives.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_executive_plans_account_id", "ai_executive_plans", ["account_id"])
    op.create_index("ix_ai_executive_plans_project_id", "ai_executive_plans", ["project_id"])
    op.create_index("ix_ai_executive_plans_project", "ai_executive_plans", ["project_id"])
    op.create_index("ix_ai_executive_plans_objective", "ai_executive_plans", ["objective_id"])
    op.create_index("ix_ai_executive_plans_account", "ai_executive_plans", ["account_id"])

    op.create_table(
        "business_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=True),
        sa.Column("action_type", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="generated"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("reasoning", _json(), nullable=False, server_default="[]"),
        sa.Column("expected_impact", _json(), nullable=False, server_default="{}"),
        sa.Column("source_modules", _json(), nullable=False, server_default="[]"),
        sa.Column("apply_payload", _json(), nullable=False, server_default="{}"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["ai_executive_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_business_actions_account_id", "business_actions", ["account_id"])
    op.create_index("ix_business_actions_project_id", "business_actions", ["project_id"])
    op.create_index(
        "ix_business_actions_project_status", "business_actions", ["project_id", "status"]
    )
    op.create_index("ix_business_actions_plan", "business_actions", ["plan_id"])


def downgrade() -> None:
    op.drop_index("ix_business_actions_plan", table_name="business_actions")
    op.drop_index("ix_business_actions_project_status", table_name="business_actions")
    op.drop_index("ix_business_actions_project_id", table_name="business_actions")
    op.drop_index("ix_business_actions_account_id", table_name="business_actions")
    op.drop_table("business_actions")

    op.drop_index("ix_ai_executive_plans_account", table_name="ai_executive_plans")
    op.drop_index("ix_ai_executive_plans_objective", table_name="ai_executive_plans")
    op.drop_index("ix_ai_executive_plans_project", table_name="ai_executive_plans")
    op.drop_index("ix_ai_executive_plans_project_id", table_name="ai_executive_plans")
    op.drop_index("ix_ai_executive_plans_account_id", table_name="ai_executive_plans")
    op.drop_table("ai_executive_plans")

    op.drop_index("ix_business_objectives_project_status", table_name="business_objectives")
    op.drop_index("ix_business_objectives_account", table_name="business_objectives")
    op.drop_index("ix_business_objectives_project_id", table_name="business_objectives")
    op.drop_index("ix_business_objectives_account_id", table_name="business_objectives")
    op.drop_table("business_objectives")
