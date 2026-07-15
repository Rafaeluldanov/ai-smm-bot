"""AI Sales & Lead Intelligence: lead events + revenue attribution + profile (v0.6.8)

Revision ID: 0050_ai_sales_intelligence
Revises: 0049_ai_campaign_manager
Create Date: 2026-07-15

Аналитический слой «контент → лид → выручка»: события лидов/выручки + строки атрибуции
+ профиль продаж. Секретов не хранит; ничего не отправляет и не меняет live/CRM.
Совместимо со SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0050_ai_sales_intelligence"
down_revision: str | None = "0049_ai_campaign_manager"
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
        "ai_lead_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=True),
        sa.Column("campaign_id", sa.Integer(), nullable=True),
        sa.Column("platform_key", sa.String(length=40), nullable=True),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="new"),
        sa.Column("source_type", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("event_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["campaign_id"], ["ai_campaigns.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_lead_events_account_id", "ai_lead_events", ["account_id"])
    op.create_index("ix_ai_lead_events_project_id", "ai_lead_events", ["project_id"])
    op.create_index(
        "ix_ai_lead_events_project_created", "ai_lead_events", ["project_id", "created_at"]
    )
    op.create_index(
        "ix_ai_lead_events_project_event", "ai_lead_events", ["project_id", "event_type"]
    )
    op.create_index("ix_ai_lead_events_post", "ai_lead_events", ["post_id"])
    op.create_index("ix_ai_lead_events_campaign", "ai_lead_events", ["campaign_id"])

    op.create_table(
        "content_revenue_attributions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=True),
        sa.Column("campaign_id", sa.Integer(), nullable=True),
        sa.Column("lead_event_id", sa.Integer(), nullable=True),
        sa.Column("attribution_model", sa.String(length=20), nullable=False),
        sa.Column("revenue_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reasoning", _json(), nullable=False, server_default="[]"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["campaign_id"], ["ai_campaigns.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_event_id"], ["ai_lead_events.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_content_revenue_attr_account_id", "content_revenue_attributions", ["account_id"]
    )
    op.create_index(
        "ix_content_revenue_attr_project_id", "content_revenue_attributions", ["project_id"]
    )
    op.create_index(
        "ix_content_revenue_attr_project_model",
        "content_revenue_attributions",
        ["project_id", "attribution_model"],
    )
    op.create_index("ix_content_revenue_attr_post", "content_revenue_attributions", ["post_id"])
    op.create_index(
        "ix_content_revenue_attr_campaign", "content_revenue_attributions", ["campaign_id"]
    )

    op.create_table(
        "sales_intelligence_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="learning"),
        sa.Column("best_lead_topics", _json(), nullable=False, server_default="[]"),
        sa.Column("best_campaigns", _json(), nullable=False, server_default="[]"),
        sa.Column("best_cta", _json(), nullable=False, server_default="[]"),
        sa.Column("best_platforms", _json(), nullable=False, server_default="[]"),
        sa.Column("conversion_patterns", _json(), nullable=False, server_default="{}"),
        sa.Column("revenue_insights", _json(), nullable=False, server_default="{}"),
        sa.Column("last_analysis_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sales_intelligence_profiles_project",
        "sales_intelligence_profiles",
        ["project_id"],
        unique=True,
    )
    op.create_index(
        "ix_sales_intelligence_profiles_account", "sales_intelligence_profiles", ["account_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_sales_intelligence_profiles_account", table_name="sales_intelligence_profiles"
    )
    op.drop_index(
        "ix_sales_intelligence_profiles_project", table_name="sales_intelligence_profiles"
    )
    op.drop_table("sales_intelligence_profiles")

    op.drop_index("ix_content_revenue_attr_campaign", table_name="content_revenue_attributions")
    op.drop_index("ix_content_revenue_attr_post", table_name="content_revenue_attributions")
    op.drop_index(
        "ix_content_revenue_attr_project_model", table_name="content_revenue_attributions"
    )
    op.drop_index("ix_content_revenue_attr_project_id", table_name="content_revenue_attributions")
    op.drop_index("ix_content_revenue_attr_account_id", table_name="content_revenue_attributions")
    op.drop_table("content_revenue_attributions")

    op.drop_index("ix_ai_lead_events_campaign", table_name="ai_lead_events")
    op.drop_index("ix_ai_lead_events_post", table_name="ai_lead_events")
    op.drop_index("ix_ai_lead_events_project_event", table_name="ai_lead_events")
    op.drop_index("ix_ai_lead_events_project_created", table_name="ai_lead_events")
    op.drop_index("ix_ai_lead_events_project_id", table_name="ai_lead_events")
    op.drop_index("ix_ai_lead_events_account_id", table_name="ai_lead_events")
    op.drop_table("ai_lead_events")
