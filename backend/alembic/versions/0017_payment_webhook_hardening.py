"""Payment webhook hardening: идемпотентность и статус обработки

Revision ID: 0017_payment_webhook_hardening
Revises: 0016_auth_sessions
Create Date: 2026-07-11

Добавляет в ``payment_webhook_logs`` поля идемпотентности/наблюдаемости:
``provider_event_id`` (id события провайдера — дубликаты игнорируются),
``status`` (received | processed | ignored | failed), ``processed_at``,
``error_message``. Совместимо со SQLite (тесты) и PostgreSQL (prod).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017_payment_webhook_hardening"
down_revision: str | None = "0016_auth_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "payment_webhook_logs",
        sa.Column("provider_event_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "payment_webhook_logs",
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="received",
        ),
    )
    op.add_column(
        "payment_webhook_logs",
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "payment_webhook_logs",
        sa.Column("error_message", sa.String(length=1000), nullable=True),
    )
    op.create_index(
        "ix_payment_webhook_logs_provider_event_id",
        "payment_webhook_logs",
        ["provider_event_id"],
    )
    op.create_index(
        "ix_payment_webhook_logs_status",
        "payment_webhook_logs",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_payment_webhook_logs_status", table_name="payment_webhook_logs")
    op.drop_index("ix_payment_webhook_logs_provider_event_id", table_name="payment_webhook_logs")
    op.drop_column("payment_webhook_logs", "error_message")
    op.drop_column("payment_webhook_logs", "processed_at")
    op.drop_column("payment_webhook_logs", "status")
    op.drop_column("payment_webhook_logs", "provider_event_id")
