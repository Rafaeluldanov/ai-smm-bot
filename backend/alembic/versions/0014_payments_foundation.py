"""Payments foundation: billing profiles, invoices, transactions, webhook logs

Revision ID: 0014_payments_foundation
Revises: 0013_saas_accounts_and_billing
Create Date: 2026-07-11

Реальных платежей нет: таблицы обслуживают mock/sandbox-счета. Совместимо со SQLite
(тесты) и PostgreSQL (JSONB через variant).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014_payments_foundation"
down_revision: str | None = "0013_saas_accounts_and_billing"
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
        "billing_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("customer_type", sa.String(length=20), nullable=False),
        sa.Column("legal_name", sa.String(length=500), nullable=True),
        sa.Column("inn", sa.String(length=20), nullable=True),
        sa.Column("kpp", sa.String(length=20), nullable=True),
        sa.Column("ogrn", sa.String(length=20), nullable=True),
        sa.Column("ogrnip", sa.String(length=20), nullable=True),
        sa.Column("legal_address", sa.String(length=1000), nullable=True),
        sa.Column("contact_name", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_billing_profiles_account_id", "billing_profiles", ["account_id"])
    op.create_index("ix_billing_profiles_status", "billing_profiles", ["status"])

    op.create_table(
        "payment_invoices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("method", sa.String(length=40), nullable=False),
        sa.Column("amount_units", sa.Integer(), nullable=False),
        sa.Column("amount_rub", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("payment_url", sa.String(length=1024), nullable=True),
        sa.Column("qr_payload", sa.String(length=1024), nullable=True),
        sa.Column("provider_payment_id", sa.String(length=255), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("invoice_metadata", _json(), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_payment_invoice_idempotency_key"),
    )
    op.create_index("ix_payment_invoices_account_id", "payment_invoices", ["account_id"])
    op.create_index("ix_payment_invoices_provider", "payment_invoices", ["provider"])
    op.create_index("ix_payment_invoices_status", "payment_invoices", ["status"])
    op.create_index(
        "ix_payment_invoices_provider_payment_id", "payment_invoices", ["provider_payment_id"]
    )

    op.create_table(
        "payment_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_payment_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("amount_units", sa.Integer(), nullable=False),
        sa.Column("amount_rub", sa.Integer(), nullable=False),
        sa.Column("raw_payload_sanitized", _json(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["invoice_id"], ["payment_invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payment_transactions_invoice_id", "payment_transactions", ["invoice_id"])
    op.create_index("ix_payment_transactions_account_id", "payment_transactions", ["account_id"])
    op.create_index(
        "ix_payment_transactions_provider_payment_id",
        "payment_transactions",
        ["provider_payment_id"],
    )

    op.create_table(
        "payment_webhook_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("provider_payment_id", sa.String(length=255), nullable=True),
        sa.Column("payload_sanitized", _json(), nullable=False),
        sa.Column("signature_valid", sa.Boolean(), nullable=False),
        sa.Column("processed", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payment_webhook_logs_provider", "payment_webhook_logs", ["provider"])
    op.create_index(
        "ix_payment_webhook_logs_provider_payment_id",
        "payment_webhook_logs",
        ["provider_payment_id"],
    )


def downgrade() -> None:
    op.drop_table("payment_webhook_logs")
    op.drop_table("payment_transactions")
    op.drop_table("payment_invoices")
    op.drop_table("billing_profiles")
