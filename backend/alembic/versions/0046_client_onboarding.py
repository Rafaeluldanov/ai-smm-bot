"""Client onboarding: sessions + step results (v0.6.4)

Revision ID: 0046_client_onboarding
Revises: 0045_telegram_live_runbook
Create Date: 2026-07-14

Клиентский онбординг-мастер (5 шагов): сессии + результаты шагов. Секретов/токенов не хранит;
live не включает. Совместимо со SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0046_client_onboarding"
down_revision: str | None = "0045_telegram_live_runbook"
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
        "onboarding_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="started"),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("business_data", _json(), nullable=False, server_default="{}"),
        sa.Column("media_data", _json(), nullable=False, server_default="{}"),
        sa.Column("platform_data", _json(), nullable=False, server_default="{}"),
        sa.Column("goal_data", _json(), nullable=False, server_default="{}"),
        sa.Column("completion_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_onb_account_id", "onboarding_sessions", ["account_id"])
    op.create_index("ix_onb_user_id", "onboarding_sessions", ["user_id"])
    op.create_index("ix_onb_project_id", "onboarding_sessions", ["project_id"])
    op.create_index("ix_onb_status", "onboarding_sessions", ["status"])

    op.create_table(
        "onboarding_step_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("step_name", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="started"),
        sa.Column("input_data", _json(), nullable=False, server_default="{}"),
        sa.Column("output_data", _json(), nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["session_id"], ["onboarding_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_onbstep_session_id", "onboarding_step_results", ["session_id"])
    op.create_index("ix_onbstep_step_name", "onboarding_step_results", ["step_name"])


def downgrade() -> None:
    op.drop_index("ix_onbstep_step_name", table_name="onboarding_step_results")
    op.drop_index("ix_onbstep_session_id", table_name="onboarding_step_results")
    op.drop_table("onboarding_step_results")

    op.drop_index("ix_onb_status", table_name="onboarding_sessions")
    op.drop_index("ix_onb_project_id", table_name="onboarding_sessions")
    op.drop_index("ix_onb_user_id", table_name="onboarding_sessions")
    op.drop_index("ix_onb_account_id", table_name="onboarding_sessions")
    op.drop_table("onboarding_sessions")
