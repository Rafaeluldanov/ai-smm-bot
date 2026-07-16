"""AI Continuous Improvement: experiences + events + patterns + improvements (v0.8.0)

Revision ID: 0062_ai_continuous_improvement
Revises: 0061_ai_performance_intelligence
Create Date: 2026-07-16

Learning/аналитический слой (Continuous Improvement): цикл обучения бизнеса на истории решений и
результатов — память опыта, события обучения, паттерны, backlog улучшений. Performance Result →
Experience Memory → Learning Event → Pattern Analysis → Improvement Backlog → Owner Review.
Секретов не хранит; НЕ меняет бизнес/стратегию/KPI/CRM/бюджет, НЕ выполняет задачи/улучшения, НЕ
запускает рекламу/публикации. SQLite+PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic (<=32 chars: alembic_version.version_num is varchar(32)).
revision: str = "0062_ai_continuous_improvement"
down_revision: str | None = "0061_ai_performance_intelligence"
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
        "experience_memories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("experience_type", sa.String(length=20), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("context", _json(), nullable=False, server_default="{}"),
        sa.Column("expected_result", _json(), nullable=False, server_default="{}"),
        sa.Column("actual_result", _json(), nullable=False, server_default="{}"),
        sa.Column("outcome", sa.String(length=20), nullable=False, server_default="neutral"),
        sa.Column("lessons", _json(), nullable=False, server_default="[]"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_experience_memories_account_id", "experience_memories", ["account_id"])
    op.create_index("ix_experience_memories_project_id", "experience_memories", ["project_id"])
    op.create_index(
        "ix_experience_memories_project_type",
        "experience_memories",
        ["project_id", "experience_type"],
    )

    op.create_table(
        "learning_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("experience_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("impact", _json(), nullable=False, server_default="{}"),
        _created_at(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["experience_id"], ["experience_memories.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_learning_events_account_id", "learning_events", ["account_id"])
    op.create_index("ix_learning_events_project_id", "learning_events", ["project_id"])
    op.create_index("ix_learning_events_experience_id", "learning_events", ["experience_id"])

    op.create_table(
        "ai_patterns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("pattern_type", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("signals", _json(), nullable=False, server_default="[]"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_patterns_account_id", "ai_patterns", ["account_id"])
    op.create_index("ix_ai_patterns_project_id", "ai_patterns", ["project_id"])
    op.create_index("ix_ai_patterns_project_type", "ai_patterns", ["project_id", "pattern_type"])

    op.create_table(
        "improvement_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("pattern_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="identified"),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("expected_impact", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_improvement_items_account_id", "improvement_items", ["account_id"])
    op.create_index("ix_improvement_items_project_id", "improvement_items", ["project_id"])
    op.create_index(
        "ix_improvement_items_project_status", "improvement_items", ["project_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_improvement_items_project_status", table_name="improvement_items")
    op.drop_index("ix_improvement_items_project_id", table_name="improvement_items")
    op.drop_index("ix_improvement_items_account_id", table_name="improvement_items")
    op.drop_table("improvement_items")

    op.drop_index("ix_ai_patterns_project_type", table_name="ai_patterns")
    op.drop_index("ix_ai_patterns_project_id", table_name="ai_patterns")
    op.drop_index("ix_ai_patterns_account_id", table_name="ai_patterns")
    op.drop_table("ai_patterns")

    op.drop_index("ix_learning_events_experience_id", table_name="learning_events")
    op.drop_index("ix_learning_events_project_id", table_name="learning_events")
    op.drop_index("ix_learning_events_account_id", table_name="learning_events")
    op.drop_table("learning_events")

    op.drop_index("ix_experience_memories_project_type", table_name="experience_memories")
    op.drop_index("ix_experience_memories_project_id", table_name="experience_memories")
    op.drop_index("ix_experience_memories_account_id", table_name="experience_memories")
    op.drop_table("experience_memories")
