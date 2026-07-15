"""AI Campaign Manager: campaigns + stages + recommendations (v0.6.7)

Revision ID: 0049_ai_campaign_manager
Revises: 0048_content_strategy
Create Date: 2026-07-15

Слой автономного кампейн-менеджера: кампания (цель/продукт/аудитория/период/стратегия)
+ этапы воронки + рекомендации (Review → Accept → Apply). Секретов не хранит; live не
включает; активный календарь сам не меняет. Совместимо со SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0049_ai_campaign_manager"
down_revision: str | None = "0048_content_strategy"
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
        "ai_campaigns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("goal", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("product_context", _json(), nullable=False, server_default="{}"),
        sa.Column("audience_context", _json(), nullable=False, server_default="{}"),
        sa.Column("business_context", _json(), nullable=False, server_default="{}"),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("strategy_snapshot", _json(), nullable=False, server_default="{}"),
        sa.Column("kpi_targets", _json(), nullable=False, server_default="{}"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_campaigns_account_id", "ai_campaigns", ["account_id"])
    op.create_index("ix_ai_campaigns_project_id", "ai_campaigns", ["project_id"])
    op.create_index("ix_ai_campaigns_account", "ai_campaigns", ["account_id"])
    op.create_index("ix_ai_campaigns_project_status", "ai_campaigns", ["project_id", "status"])

    op.create_table(
        "ai_campaign_stages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("stage_type", sa.String(length=20), nullable=False),
        sa.Column("order_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("goal", sa.String(length=64), nullable=True),
        sa.Column("content_pillars", _json(), nullable=False, server_default="[]"),
        sa.Column("recommended_formats", _json(), nullable=False, server_default="[]"),
        sa.Column("recommended_topics", _json(), nullable=False, server_default="[]"),
        sa.Column("cta_strategy", _json(), nullable=False, server_default="{}"),
        sa.Column("duration_days", sa.Integer(), nullable=False, server_default="7"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["campaign_id"], ["ai_campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_campaign_stages_campaign_id", "ai_campaign_stages", ["campaign_id"])
    op.create_index(
        "ix_ai_campaign_stages_campaign", "ai_campaign_stages", ["campaign_id", "order_number"]
    )

    op.create_table(
        "ai_campaign_recommendations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("recommendation_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="generated"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("reasoning", _json(), nullable=False, server_default="[]"),
        sa.Column("expected_result", _json(), nullable=False, server_default="{}"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["campaign_id"], ["ai_campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_campaign_recs_campaign_id", "ai_campaign_recommendations", ["campaign_id"]
    )
    op.create_index(
        "ix_ai_campaign_recs_campaign_status",
        "ai_campaign_recommendations",
        ["campaign_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_campaign_recs_campaign_status", table_name="ai_campaign_recommendations")
    op.drop_index("ix_ai_campaign_recs_campaign_id", table_name="ai_campaign_recommendations")
    op.drop_table("ai_campaign_recommendations")

    op.drop_index("ix_ai_campaign_stages_campaign", table_name="ai_campaign_stages")
    op.drop_index("ix_ai_campaign_stages_campaign_id", table_name="ai_campaign_stages")
    op.drop_table("ai_campaign_stages")

    op.drop_index("ix_ai_campaigns_project_status", table_name="ai_campaigns")
    op.drop_index("ix_ai_campaigns_account", table_name="ai_campaigns")
    op.drop_index("ix_ai_campaigns_project_id", table_name="ai_campaigns")
    op.drop_index("ix_ai_campaigns_account_id", table_name="ai_campaigns")
    op.drop_table("ai_campaigns")
