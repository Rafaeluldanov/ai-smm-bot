"""Autonomous content strategist: profile + recommendations (v0.6.6)

Revision ID: 0048_content_strategy
Revises: 0047_ai_learning_loop
Create Date: 2026-07-14

Слой рекомендаций автономного контент-стратега: профиль стратегии (одна строка на
проект) + поток рекомендаций (Recommendation → Review → Apply). Секретов/токенов не
хранит; live не включает; активный календарь сам не меняет. SQLite + PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0048_content_strategy"
down_revision: str | None = "0047_ai_learning_loop"
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
        "content_strategy_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="learning"),
        sa.Column("business_goal", sa.String(length=64), nullable=True),
        sa.Column("target_audience", _json(), nullable=False, server_default="{}"),
        sa.Column("brand_positioning", _json(), nullable=False, server_default="{}"),
        sa.Column("content_pillars", _json(), nullable=False, server_default="[]"),
        sa.Column("preferred_topics", _json(), nullable=False, server_default="[]"),
        sa.Column("avoided_topics", _json(), nullable=False, server_default="[]"),
        sa.Column("preferred_formats", _json(), nullable=False, server_default="[]"),
        sa.Column("preferred_platforms", _json(), nullable=False, server_default="[]"),
        sa.Column("posting_strategy", _json(), nullable=False, server_default="{}"),
        sa.Column("seasonality_rules", _json(), nullable=False, server_default="{}"),
        sa.Column("last_strategy_update", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_content_strategy_profiles_project",
        "content_strategy_profiles",
        ["project_id"],
        unique=True,
    )
    op.create_index(
        "ix_content_strategy_profiles_account", "content_strategy_profiles", ["account_id"]
    )

    op.create_table(
        "content_strategy_recommendations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("recommendation_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="generated"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("reasoning", _json(), nullable=False, server_default="[]"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("source_signals", _json(), nullable=False, server_default="[]"),
        sa.Column("expected_impact", _json(), nullable=False, server_default="{}"),
        sa.Column("apply_payload", _json(), nullable=False, server_default="{}"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_content_strategy_recs_account", "content_strategy_recommendations", ["account_id"]
    )
    op.create_index(
        "ix_content_strategy_recs_project", "content_strategy_recommendations", ["project_id"]
    )
    op.create_index(
        "ix_content_strategy_recs_project_status",
        "content_strategy_recommendations",
        ["project_id", "status"],
    )
    op.create_index(
        "ix_content_strategy_recs_project_type",
        "content_strategy_recommendations",
        ["project_id", "recommendation_type"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_content_strategy_recs_project_type", table_name="content_strategy_recommendations"
    )
    op.drop_index(
        "ix_content_strategy_recs_project_status", table_name="content_strategy_recommendations"
    )
    op.drop_index("ix_content_strategy_recs_project", table_name="content_strategy_recommendations")
    op.drop_index("ix_content_strategy_recs_account", table_name="content_strategy_recommendations")
    op.drop_table("content_strategy_recommendations")

    op.drop_index("ix_content_strategy_profiles_account", table_name="content_strategy_profiles")
    op.drop_index("ix_content_strategy_profiles_project", table_name="content_strategy_profiles")
    op.drop_table("content_strategy_profiles")
