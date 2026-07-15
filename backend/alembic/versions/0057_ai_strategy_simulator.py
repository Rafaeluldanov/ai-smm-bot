"""AI Strategy Simulator: simulations + forecasts + comparisons (v0.7.5)

Revision ID: 0057_ai_strategy_simulator
Revises: 0056_ai_decision_engine
Create Date: 2026-07-15

Аналитический слой (Strategy Simulator): берёт сценарий решения (Decision Engine) и моделирует
последствия на горизонте 30/60/90 дней — прогноз метрик, уверенность, сравнение сценариев,
рекомендация (Decision Scenario → Simulation → Forecast → Comparison → Recommendation). Секретов
не хранит; НЕ гарантирует прибыль, НЕ меняет бизнес/CRM/бюджет/live/публикации/рекламу, НЕ
выполняет стратегии. SQLite+PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic (<=32 chars: alembic_version.version_num is varchar(32)).
revision: str = "0057_ai_strategy_simulator"
down_revision: str | None = "0056_ai_decision_engine"
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
        "strategy_simulations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("decision_id", sa.Integer(), nullable=True),
        sa.Column("scenario_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="generated"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("assumptions", _json(), nullable=False, server_default="[]"),
        sa.Column(
            "simulation_period", sa.String(length=20), nullable=False, server_default="90_days"
        ),
        sa.Column(
            "confidence_level", sa.String(length=20), nullable=False, server_default="medium"
        ),
        sa.Column("overall_score", sa.Float(), nullable=False, server_default="0"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decision_id"], ["ai_decisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["scenario_id"], ["decision_scenarios.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_strategy_simulations_account_id", "strategy_simulations", ["account_id"])
    op.create_index("ix_strategy_simulations_project_id", "strategy_simulations", ["project_id"])
    op.create_index("ix_strategy_simulations_decision_id", "strategy_simulations", ["decision_id"])
    op.create_index("ix_strategy_simulations_scenario_id", "strategy_simulations", ["scenario_id"])
    op.create_index(
        "ix_strategy_simulations_project_status",
        "strategy_simulations",
        ["project_id", "status"],
    )

    op.create_table(
        "forecast_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("simulation_id", sa.Integer(), nullable=False),
        sa.Column("metric", sa.String(length=20), nullable=False),
        sa.Column("period", sa.String(length=20), nullable=False),
        sa.Column("baseline_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("forecast_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("change_percent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reasoning", _json(), nullable=False, server_default="[]"),
        _created_at(),
        sa.ForeignKeyConstraint(["simulation_id"], ["strategy_simulations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_forecast_results_simulation_id", "forecast_results", ["simulation_id"])

    op.create_table(
        "scenario_comparisons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("decision_id", sa.Integer(), nullable=False),
        sa.Column("winner_scenario_id", sa.Integer(), nullable=True),
        sa.Column("comparison_data", _json(), nullable=False, server_default="{}"),
        sa.Column("score_difference", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reasoning", _json(), nullable=False, server_default="[]"),
        _created_at(),
        sa.ForeignKeyConstraint(["decision_id"], ["ai_decisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scenario_comparisons_decision_id", "scenario_comparisons", ["decision_id"])


def downgrade() -> None:
    op.drop_index("ix_scenario_comparisons_decision_id", table_name="scenario_comparisons")
    op.drop_table("scenario_comparisons")

    op.drop_index("ix_forecast_results_simulation_id", table_name="forecast_results")
    op.drop_table("forecast_results")

    op.drop_index("ix_strategy_simulations_project_status", table_name="strategy_simulations")
    op.drop_index("ix_strategy_simulations_scenario_id", table_name="strategy_simulations")
    op.drop_index("ix_strategy_simulations_decision_id", table_name="strategy_simulations")
    op.drop_index("ix_strategy_simulations_project_id", table_name="strategy_simulations")
    op.drop_index("ix_strategy_simulations_account_id", table_name="strategy_simulations")
    op.drop_table("strategy_simulations")
