"""AI Business Forecasting: forecasts + metrics + roadmaps (v0.7.6)

Revision ID: 0058_ai_business_forecasting
Revises: 0057_ai_strategy_simulator
Create Date: 2026-07-15

Аналитический прогнозный слой (Business Forecasting Engine): текущее состояние бизнеса →
прогноз на 3/6/12 месяцев (KPI-проекция + поправка на риск + бизнес-outlook + roadmap).
Business State → Forecast Model → KPI Projection → Risk Adjustment → Business Outlook → Owner
Review. Секретов не хранит; НЕ гарантирует прибыль, НЕ обещает финансовый результат, НЕ меняет
бизнес/CRM/бюджет, НЕ выполняет стратегии, НЕ ходит во внешние API. SQLite+PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic (<=32 chars: alembic_version.version_num is varchar(32)).
revision: str = "0058_ai_business_forecasting"
down_revision: str | None = "0057_ai_strategy_simulator"
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
        "business_forecasts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="generated"),
        sa.Column("horizon", sa.String(length=20), nullable=False, server_default="12_months"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("baseline_state", _json(), nullable=False, server_default="{}"),
        sa.Column("forecast_state", _json(), nullable=False, server_default="{}"),
        sa.Column("assumptions", _json(), nullable=False, server_default="[]"),
        sa.Column("risk_level", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_business_forecasts_account_id", "business_forecasts", ["account_id"])
    op.create_index("ix_business_forecasts_project_id", "business_forecasts", ["project_id"])
    op.create_index(
        "ix_business_forecasts_project_status", "business_forecasts", ["project_id", "status"]
    )

    op.create_table(
        "forecast_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("forecast_id", sa.Integer(), nullable=False),
        sa.Column("metric", sa.String(length=20), nullable=False),
        sa.Column("baseline_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("forecast_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("change_percent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reasoning", _json(), nullable=False, server_default="[]"),
        _created_at(),
        sa.ForeignKeyConstraint(["forecast_id"], ["business_forecasts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_forecast_metrics_forecast_id", "forecast_metrics", ["forecast_id"])

    op.create_table(
        "business_roadmaps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("forecast_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("quarters", _json(), nullable=False, server_default="[]"),
        sa.Column("milestones", _json(), nullable=False, server_default="[]"),
        sa.Column("risks", _json(), nullable=False, server_default="[]"),
        sa.Column("recommendations", _json(), nullable=False, server_default="[]"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["forecast_id"], ["business_forecasts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_business_roadmaps_forecast_id", "business_roadmaps", ["forecast_id"])


def downgrade() -> None:
    op.drop_index("ix_business_roadmaps_forecast_id", table_name="business_roadmaps")
    op.drop_table("business_roadmaps")

    op.drop_index("ix_forecast_metrics_forecast_id", table_name="forecast_metrics")
    op.drop_table("forecast_metrics")

    op.drop_index("ix_business_forecasts_project_status", table_name="business_forecasts")
    op.drop_index("ix_business_forecasts_project_id", table_name="business_forecasts")
    op.drop_index("ix_business_forecasts_account_id", table_name="business_forecasts")
    op.drop_table("business_forecasts")
