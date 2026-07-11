"""Schedule automation: прогоны расписаний (schedule_runs)

Revision ID: 0020_schedule_runs
Revises: 0019_public_media_links
Create Date: 2026-07-11

Движок автоматизации расписаний: факт обработки due-задачи (создан draft / пропущен /
ошибка). Только draft/needs_review — живой публикации нет. ``idempotency_key`` unique
защищает от дублей при повторном запуске. Секретов в run_metadata нет. Совместимо со
SQLite (тесты) и PostgreSQL (JSONB variant).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0020_schedule_runs"
down_revision: str | None = "0019_public_media_links"
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
        "schedule_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("platform_key", sa.String(length=40), nullable=False),
        sa.Column("publishing_plan_id", sa.Integer(), nullable=True),
        sa.Column("schedule_key", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("run_date", sa.String(length=20), nullable=False),
        sa.Column("planned_time", sa.String(length=10), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="planned"),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=True),
        sa.Column("publication_id", sa.Integer(), nullable=True),
        sa.Column("units_estimated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("units_charged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("run_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["publishing_plan_id"], ["crm_publishing_plans.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["publication_id"], ["post_publications.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_schedule_runs_idempotency_key", "schedule_runs", ["idempotency_key"], unique=True
    )
    op.create_index("ix_schedule_runs_account_id", "schedule_runs", ["account_id"])
    op.create_index("ix_schedule_runs_project_id", "schedule_runs", ["project_id"])
    op.create_index("ix_schedule_runs_platform_key", "schedule_runs", ["platform_key"])
    op.create_index("ix_schedule_runs_status", "schedule_runs", ["status"])
    op.create_index("ix_schedule_runs_run_date", "schedule_runs", ["run_date"])


def downgrade() -> None:
    op.drop_index("ix_schedule_runs_run_date", table_name="schedule_runs")
    op.drop_index("ix_schedule_runs_status", table_name="schedule_runs")
    op.drop_index("ix_schedule_runs_platform_key", table_name="schedule_runs")
    op.drop_index("ix_schedule_runs_project_id", table_name="schedule_runs")
    op.drop_index("ix_schedule_runs_account_id", table_name="schedule_runs")
    op.drop_index("ix_schedule_runs_idempotency_key", table_name="schedule_runs")
    op.drop_table("schedule_runs")
