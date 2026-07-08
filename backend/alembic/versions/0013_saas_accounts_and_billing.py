"""SaaS: users, accounts, memberships, billing (units) + projects.account_id

Revision ID: 0013_saas_accounts_and_billing
Revises: 0012_post_generation_notes
Create Date: 2026-07-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013_saas_accounts_and_billing"
down_revision: str | None = "0012_post_generation_notes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json() -> sa.types.TypeEngine:
    """JSON-тип: JSONB на PostgreSQL, JSON на прочих СУБД."""
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
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_superuser", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_accounts_slug", "accounts", ["slug"], unique=True)
    op.create_index("ix_accounts_owner_user_id", "accounts", ["owner_user_id"])
    op.create_index("ix_accounts_status", "accounts", ["status"])

    op.create_table(
        "account_memberships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "user_id", name="uq_account_membership_account_user"),
    )
    op.create_index("ix_account_memberships_account_id", "account_memberships", ["account_id"])
    op.create_index("ix_account_memberships_user_id", "account_memberships", ["user_id"])

    op.create_table(
        "tariff_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("included_units", sa.Integer(), nullable=False),
        sa.Column("unit_price_rub", sa.Integer(), nullable=False),
        sa.Column("markup_percent", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tariff_plans_slug", "tariff_plans", ["slug"], unique=True)
    op.create_index("ix_tariff_plans_status", "tariff_plans", ["status"])

    op.create_table(
        "billing_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("balance_units", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("tariff_plan_slug", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_billing_accounts_account_id", "billing_accounts", ["account_id"], unique=True
    )
    op.create_index("ix_billing_accounts_status", "billing_accounts", ["status"])

    op.create_table(
        "billing_ledger_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("billing_account_id", sa.Integer(), nullable=False),
        sa.Column("entry_type", sa.String(length=20), nullable=False),
        sa.Column("amount_units", sa.Integer(), nullable=False),
        sa.Column("balance_after_units", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("entry_metadata", _json(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["billing_account_id"], ["billing_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_billing_ledger_idempotency_key"),
    )
    op.create_index(
        "ix_billing_ledger_entries_billing_account_id",
        "billing_ledger_entries",
        ["billing_account_id"],
    )
    op.create_index(
        "ix_billing_ledger_entries_entry_type", "billing_ledger_entries", ["entry_type"]
    )

    op.create_table(
        "usage_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("post_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("provider_cost_estimate", sa.Integer(), nullable=True),
        sa.Column("markup_percent", sa.Integer(), nullable=True),
        sa.Column("event_metadata", _json(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usage_events_account_id", "usage_events", ["account_id"])
    op.create_index("ix_usage_events_project_id", "usage_events", ["project_id"])
    op.create_index("ix_usage_events_post_id", "usage_events", ["post_id"])
    op.create_index("ix_usage_events_event_type", "usage_events", ["event_type"])

    # projects.account_id — nullable, чтобы старые CRM/seed-проекты не сломались.
    op.add_column("projects", sa.Column("account_id", sa.Integer(), nullable=True))
    op.create_index("ix_projects_account_id", "projects", ["account_id"])
    op.create_foreign_key(
        "fk_projects_account_id",
        "projects",
        "accounts",
        ["account_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_projects_account_id", "projects", type_="foreignkey")
    op.drop_index("ix_projects_account_id", table_name="projects")
    op.drop_column("projects", "account_id")

    op.drop_table("usage_events")
    op.drop_table("billing_ledger_entries")
    op.drop_table("billing_accounts")
    op.drop_table("tariff_plans")
    op.drop_table("account_memberships")
    op.drop_table("accounts")
    op.drop_table("users")
