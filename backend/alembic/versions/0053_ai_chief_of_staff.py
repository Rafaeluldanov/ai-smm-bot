"""AI Chief of Staff: executive briefings + owner tasks + decision memory (v0.7.1)

Revision ID: 0053_ai_chief_of_staff
Revises: 0052_autonomous_business_os
Create Date: 2026-07-15

Персональный AI-ассистент владельца (Executive Assistant Layer): ежедневные/еженедельные
брифинги + задачи владельца + долговременная память решений (Analyze → Briefing →
Recommend → Approve → Task). Секретов не хранит; НЕ выполняет задачи, НЕ меняет
CRM/бюджет/продажи/live/публикации. Совместимо со SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0053_ai_chief_of_staff"
down_revision: str | None = "0052_autonomous_business_os"
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
        "executive_briefings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="generated"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("business_state", _json(), nullable=False, server_default="{}"),
        sa.Column("key_changes", _json(), nullable=False, server_default="[]"),
        sa.Column("risks", _json(), nullable=False, server_default="[]"),
        sa.Column("opportunities", _json(), nullable=False, server_default="[]"),
        sa.Column("recommended_actions", _json(), nullable=False, server_default="[]"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_executive_briefings_account_id", "executive_briefings", ["account_id"])
    op.create_index("ix_executive_briefings_project_id", "executive_briefings", ["project_id"])
    op.create_index("ix_executive_briefings_account", "executive_briefings", ["account_id"])
    op.create_index(
        "ix_executive_briefings_project_type", "executive_briefings", ["project_id", "type"]
    )

    op.create_table(
        "ai_business_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("briefing_id", sa.Integer(), nullable=True),
        sa.Column("task_type", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("priority_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="suggested"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("reasoning", _json(), nullable=False, server_default="[]"),
        sa.Column("expected_impact", _json(), nullable=False, server_default="{}"),
        sa.Column("source_modules", _json(), nullable=False, server_default="[]"),
        sa.Column("accepted_by_user_id", sa.Integer(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["briefing_id"], ["executive_briefings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["accepted_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_business_tasks_account_id", "ai_business_tasks", ["account_id"])
    op.create_index("ix_ai_business_tasks_project_id", "ai_business_tasks", ["project_id"])
    op.create_index(
        "ix_ai_business_tasks_project_status", "ai_business_tasks", ["project_id", "status"]
    )
    op.create_index("ix_ai_business_tasks_briefing", "ai_business_tasks", ["briefing_id"])

    op.create_table(
        "business_decision_memories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("decision_type", sa.String(length=20), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("value", _json(), nullable=False, server_default="{}"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_business_decision_memories_account_id", "business_decision_memories", ["account_id"]
    )
    op.create_index(
        "ix_business_decision_memories_project_id", "business_decision_memories", ["project_id"]
    )
    op.create_index(
        "ix_business_decision_memories_account", "business_decision_memories", ["account_id"]
    )
    op.create_index(
        "ix_business_decision_memories_project_active",
        "business_decision_memories",
        ["project_id", "active"],
    )
    # Одна активная запись на (project_id, key) — частичный уникальный индекс.
    op.create_index(
        "uq_business_decision_active_key",
        "business_decision_memories",
        ["project_id", "key"],
        unique=True,
        postgresql_where=sa.text("active"),
        sqlite_where=sa.text("active"),
    )


def downgrade() -> None:
    op.drop_index("uq_business_decision_active_key", table_name="business_decision_memories")
    op.drop_index(
        "ix_business_decision_memories_project_active", table_name="business_decision_memories"
    )
    op.drop_index("ix_business_decision_memories_account", table_name="business_decision_memories")
    op.drop_index(
        "ix_business_decision_memories_project_id", table_name="business_decision_memories"
    )
    op.drop_index(
        "ix_business_decision_memories_account_id", table_name="business_decision_memories"
    )
    op.drop_table("business_decision_memories")

    op.drop_index("ix_ai_business_tasks_briefing", table_name="ai_business_tasks")
    op.drop_index("ix_ai_business_tasks_project_status", table_name="ai_business_tasks")
    op.drop_index("ix_ai_business_tasks_project_id", table_name="ai_business_tasks")
    op.drop_index("ix_ai_business_tasks_account_id", table_name="ai_business_tasks")
    op.drop_table("ai_business_tasks")

    op.drop_index("ix_executive_briefings_project_type", table_name="executive_briefings")
    op.drop_index("ix_executive_briefings_account", table_name="executive_briefings")
    op.drop_index("ix_executive_briefings_project_id", table_name="executive_briefings")
    op.drop_index("ix_executive_briefings_account_id", table_name="executive_briefings")
    op.drop_table("executive_briefings")
