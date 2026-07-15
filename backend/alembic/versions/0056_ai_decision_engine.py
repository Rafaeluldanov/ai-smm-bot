"""AI Decision Engine: decisions + scenarios + signals (v0.7.4)

Revision ID: 0056_ai_decision_engine
Revises: 0055_ai_operations_center
Create Date: 2026-07-15

Аналитический/рекомендательный слой (Decision Engine): решения + сценарии (варианты) +
сигналы (Problem → Options → Scenario Analysis → Recommendation → Owner Approval). Секретов
не хранит; НЕ применяет решения, НЕ меняет CRM/бюджет/продажи/live/публикации. SQLite+PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic (<=32 chars: alembic_version.version_num is varchar(32)).
revision: str = "0056_ai_decision_engine"
down_revision: str | None = "0055_ai_operations_center"
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
        "ai_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("decision_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("problem_statement", sa.Text(), nullable=True),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("context", _json(), nullable=False, server_default="{}"),
        sa.Column("recommended_scenario_id", sa.Integer(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_decisions_account_id", "ai_decisions", ["account_id"])
    op.create_index("ix_ai_decisions_project_id", "ai_decisions", ["project_id"])
    op.create_index("ix_ai_decisions_account", "ai_decisions", ["account_id"])
    op.create_index("ix_ai_decisions_project_status", "ai_decisions", ["project_id", "status"])

    op.create_table(
        "decision_scenarios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("decision_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("assumptions", _json(), nullable=False, server_default="[]"),
        sa.Column("expected_impact", _json(), nullable=False, server_default="{}"),
        sa.Column("risk_analysis", _json(), nullable=False, server_default="{}"),
        sa.Column("cost_estimate", _json(), nullable=False, server_default="{}"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="generated"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["decision_id"], ["ai_decisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_decision_scenarios_decision_id", "decision_scenarios", ["decision_id"])
    op.create_index(
        "ix_decision_scenarios_decision_status", "decision_scenarios", ["decision_id", "status"]
    )

    op.create_table(
        "decision_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("decision_id", sa.Integer(), nullable=False),
        sa.Column("source_module", sa.String(length=40), nullable=False),
        sa.Column("signal_type", sa.String(length=40), nullable=False),
        sa.Column("value", _json(), nullable=False, server_default="{}"),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["decision_id"], ["ai_decisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_decision_signals_decision_id", "decision_signals", ["decision_id"])


def downgrade() -> None:
    op.drop_index("ix_decision_signals_decision_id", table_name="decision_signals")
    op.drop_table("decision_signals")

    op.drop_index("ix_decision_scenarios_decision_status", table_name="decision_scenarios")
    op.drop_index("ix_decision_scenarios_decision_id", table_name="decision_scenarios")
    op.drop_table("decision_scenarios")

    op.drop_index("ix_ai_decisions_project_status", table_name="ai_decisions")
    op.drop_index("ix_ai_decisions_account", table_name="ai_decisions")
    op.drop_index("ix_ai_decisions_project_id", table_name="ai_decisions")
    op.drop_index("ix_ai_decisions_account_id", table_name="ai_decisions")
    op.drop_table("ai_decisions")
