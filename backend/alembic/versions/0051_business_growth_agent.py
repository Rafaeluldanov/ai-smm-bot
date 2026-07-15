"""AI Business Growth Agent: growth profile + recommendations (v0.6.9)

Revision ID: 0051_business_growth_agent
Revises: 0050_ai_sales_intelligence
Create Date: 2026-07-15

Advisory-слой роста бизнеса: профиль роста (одна строка на проект) + поток рекомендаций
(Analyze → Recommend → Review → Apply). Секретов не хранит; НЕ меняет live/CRM/бюджет.
Совместимо со SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0051_business_growth_agent"
down_revision: str | None = "0050_ai_sales_intelligence"
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
        "business_growth_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="learning"),
        sa.Column("business_goal", _json(), nullable=False, server_default="{}"),
        sa.Column("growth_targets", _json(), nullable=False, server_default="{}"),
        sa.Column("current_state", _json(), nullable=False, server_default="{}"),
        sa.Column("strengths", _json(), nullable=False, server_default="[]"),
        sa.Column("weaknesses", _json(), nullable=False, server_default="[]"),
        sa.Column("opportunities", _json(), nullable=False, server_default="[]"),
        sa.Column("risks", _json(), nullable=False, server_default="[]"),
        sa.Column("growth_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("last_analysis_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_business_growth_profiles_project",
        "business_growth_profiles",
        ["project_id"],
        unique=True,
    )
    op.create_index(
        "ix_business_growth_profiles_account", "business_growth_profiles", ["account_id"]
    )

    op.create_table(
        "business_growth_recommendations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("recommendation_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="generated"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("reasoning", _json(), nullable=False, server_default="[]"),
        sa.Column("source_signals", _json(), nullable=False, server_default="[]"),
        sa.Column("expected_impact", _json(), nullable=False, server_default="{}"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("apply_payload", _json(), nullable=False, server_default="{}"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_business_growth_recs_account", "business_growth_recommendations", ["account_id"]
    )
    op.create_index(
        "ix_business_growth_recs_project", "business_growth_recommendations", ["project_id"]
    )
    op.create_index(
        "ix_business_growth_recs_project_status",
        "business_growth_recommendations",
        ["project_id", "status"],
    )
    op.create_index(
        "ix_business_growth_recs_project_type",
        "business_growth_recommendations",
        ["project_id", "recommendation_type"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_business_growth_recs_project_type", table_name="business_growth_recommendations"
    )
    op.drop_index(
        "ix_business_growth_recs_project_status", table_name="business_growth_recommendations"
    )
    op.drop_index("ix_business_growth_recs_project", table_name="business_growth_recommendations")
    op.drop_index("ix_business_growth_recs_account", table_name="business_growth_recommendations")
    op.drop_table("business_growth_recommendations")

    op.drop_index("ix_business_growth_profiles_account", table_name="business_growth_profiles")
    op.drop_index("ix_business_growth_profiles_project", table_name="business_growth_profiles")
    op.drop_table("business_growth_profiles")
