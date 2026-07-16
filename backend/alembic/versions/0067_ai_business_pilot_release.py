"""AI Business Pilot Release: pilot goals + KPIs + feedback (v1.0.0)

Revision ID: 0067_ai_business_pilot_release
Revises: 0066_ai_business_os_pilot
Create Date: 2026-07-16

First Business Pilot: цели, KPI и feedback loop реальной компании поверх pilot-окружения. Всё
только advisory: AI анализирует/прогнозирует/рекомендует, но НЕ выполняет, НЕ меняет бизнес/CRM/
финансы, НЕ шлёт сообщений. Секретов не хранит. SQLite+PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic (<=32 chars: alembic_version.version_num is varchar(32)).
revision: str = "0067_ai_business_pilot_release"
down_revision: str | None = "0066_ai_business_os_pilot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
        "pilot_goals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("current_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("target_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unit", sa.String(length=50), nullable=False, server_default=""),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["pilot_workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pilot_goals_workspace_id", "pilot_goals", ["workspace_id"])
    op.create_index("ix_pilot_goals_workspace_status", "pilot_goals", ["workspace_id", "status"])

    op.create_table(
        "pilot_kpis",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("current_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("target_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unit", sa.String(length=50), nullable=False, server_default=""),
        sa.Column("frequency", sa.String(length=30), nullable=False, server_default="monthly"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["pilot_workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pilot_kpis_workspace_id", "pilot_kpis", ["workspace_id"])
    op.create_index("ix_pilot_kpis_workspace_status", "pilot_kpis", ["workspace_id", "status"])

    op.create_table(
        "pilot_feedbacks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("recommendation_id", sa.Integer(), nullable=True),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["pilot_workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pilot_feedbacks_workspace_id", "pilot_feedbacks", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_pilot_feedbacks_workspace_id", table_name="pilot_feedbacks")
    op.drop_table("pilot_feedbacks")

    op.drop_index("ix_pilot_kpis_workspace_status", table_name="pilot_kpis")
    op.drop_index("ix_pilot_kpis_workspace_id", table_name="pilot_kpis")
    op.drop_table("pilot_kpis")

    op.drop_index("ix_pilot_goals_workspace_status", table_name="pilot_goals")
    op.drop_index("ix_pilot_goals_workspace_id", table_name="pilot_goals")
    op.drop_table("pilot_goals")
