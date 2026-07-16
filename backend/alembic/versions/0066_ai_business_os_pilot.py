"""AI Business OS Pilot: pilot workspaces + business profiles (v0.9.1)

Revision ID: 0066_ai_business_os_pilot
Revises: 0065_ai_business_os_mvp_testing
Create Date: 2026-07-16

PILOT/launch-слой: окружение первого реального бизнес-пилота (workspace + business profile) для
advisory-анализа всей AI-цепочки. Всё только advisory: бизнес/CRM не меняются, workflow/внешние
действия не выполняются. Секретов не хранит. SQLite+PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic (<=32 chars: alembic_version.version_num is varchar(32)).
revision: str = "0066_ai_business_os_pilot"
down_revision: str | None = "0065_ai_business_os_mvp_testing"
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
        "pilot_workspaces",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("industry", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pilot_workspaces_account_id", "pilot_workspaces", ["account_id"])
    op.create_index("ix_pilot_workspaces_created_by", "pilot_workspaces", ["created_by"])

    op.create_table(
        "pilot_business_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("products", _json(), nullable=False, server_default="[]"),
        sa.Column("services", _json(), nullable=False, server_default="[]"),
        sa.Column("team", _json(), nullable=False, server_default="{}"),
        sa.Column("sales_channels", _json(), nullable=False, server_default="[]"),
        sa.Column("business_description", sa.Text(), nullable=True),
        sa.Column("current_revenue", sa.Float(), nullable=False, server_default="0"),
        sa.Column("target_revenue", sa.Float(), nullable=False, server_default="0"),
        sa.Column("kpi", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["pilot_workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pilot_business_profiles_workspace_id", "pilot_business_profiles", ["workspace_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_pilot_business_profiles_workspace_id", table_name="pilot_business_profiles")
    op.drop_table("pilot_business_profiles")

    op.drop_index("ix_pilot_workspaces_created_by", table_name="pilot_workspaces")
    op.drop_index("ix_pilot_workspaces_account_id", table_name="pilot_workspaces")
    op.drop_table("pilot_workspaces")
