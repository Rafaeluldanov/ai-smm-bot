"""AI Learning Loop: profiles + events (v0.6.5)

Revision ID: 0047_ai_learning_loop
Revises: 0046_client_onboarding
Create Date: 2026-07-14

Слой памяти AI Learning Loop: персональный профиль обучения бренда (одна строка на
проект) + поток сигналов (события). Секретов/токенов не хранит; live не включает.
Совместимо со SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0047_ai_learning_loop"
down_revision: str | None = "0046_client_onboarding"
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
        "ai_learning_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="learning"),
        sa.Column("total_posts_analyzed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_feedback_events", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("learning_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("preferred_topics", _json(), nullable=False, server_default="[]"),
        sa.Column("avoided_topics", _json(), nullable=False, server_default="[]"),
        sa.Column("preferred_formats", _json(), nullable=False, server_default="[]"),
        sa.Column("avoided_formats", _json(), nullable=False, server_default="[]"),
        sa.Column("preferred_styles", _json(), nullable=False, server_default="[]"),
        sa.Column("best_publish_times", _json(), nullable=False, server_default="[]"),
        sa.Column("best_platforms", _json(), nullable=False, server_default="[]"),
        sa.Column("content_rules", _json(), nullable=False, server_default="{}"),
        sa.Column("media_preferences", _json(), nullable=False, server_default="{}"),
        sa.Column("cta_preferences", _json(), nullable=False, server_default="{}"),
        sa.Column("last_learning_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_learning_profiles_project", "ai_learning_profiles", ["project_id"], unique=True
    )
    op.create_index("ix_ai_learning_profiles_account", "ai_learning_profiles", ["account_id"])

    op.create_table(
        "ai_learning_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="system"),
        sa.Column("event_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_learning_events_account_id", "ai_learning_events", ["account_id"])
    op.create_index("ix_ai_learning_events_project_id", "ai_learning_events", ["project_id"])
    op.create_index(
        "ix_ai_learning_events_project_created",
        "ai_learning_events",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_ai_learning_events_project_entity",
        "ai_learning_events",
        ["project_id", "entity_type", "entity_id"],
    )
    op.create_index("ix_ai_learning_events_event_type", "ai_learning_events", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_ai_learning_events_event_type", table_name="ai_learning_events")
    op.drop_index("ix_ai_learning_events_project_entity", table_name="ai_learning_events")
    op.drop_index("ix_ai_learning_events_project_created", table_name="ai_learning_events")
    op.drop_index("ix_ai_learning_events_project_id", table_name="ai_learning_events")
    op.drop_index("ix_ai_learning_events_account_id", table_name="ai_learning_events")
    op.drop_table("ai_learning_events")

    op.drop_index("ix_ai_learning_profiles_account", table_name="ai_learning_profiles")
    op.drop_index("ix_ai_learning_profiles_project", table_name="ai_learning_profiles")
    op.drop_table("ai_learning_profiles")
