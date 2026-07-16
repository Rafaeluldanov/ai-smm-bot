"""AI Business OS MVP Testing: demo workspaces + demo scenarios (v0.9.0)

Revision ID: 0065_ai_business_os_mvp_testing
Revises: 0064_ai_optimization_governance
Create Date: 2026-07-16

DEMO/testing-слой: E2E-прогон всей AI-цепочки. Business Goal → Decision → Forecast → Plan →
Execution → Performance → Learning → Optimization → Governance. Тестовые сущности demo-режима;
секретов не хранит; НЕ создаёт реальных пользователей/CRM/платежей, НЕ выполняет внешних действий.
SQLite+PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic (<=32 chars: alembic_version.version_num is varchar(32)).
revision: str = "0065_ai_business_os_mvp_testing"
down_revision: str | None = "0064_ai_optimization_governance"
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
        "demo_workspaces",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("industry", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_demo_workspaces_account_id", "demo_workspaces", ["account_id"])

    op.create_table(
        "demo_scenarios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("scenario_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("input_data", _json(), nullable=False, server_default="{}"),
        sa.Column("result_data", _json(), nullable=False, server_default="{}"),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["demo_workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_demo_scenarios_workspace_id", "demo_scenarios", ["workspace_id"])
    op.create_index(
        "ix_demo_scenarios_workspace_status", "demo_scenarios", ["workspace_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_demo_scenarios_workspace_status", table_name="demo_scenarios")
    op.drop_index("ix_demo_scenarios_workspace_id", table_name="demo_scenarios")
    op.drop_table("demo_scenarios")

    op.drop_index("ix_demo_workspaces_account_id", table_name="demo_workspaces")
    op.drop_table("demo_workspaces")
