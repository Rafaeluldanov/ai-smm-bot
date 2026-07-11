"""Self-service platform connections: поля подключения на crm_smm_resources

Revision ID: 0018_platform_connection_fields
Revises: 0017_payment_webhook_hardening
Create Date: 2026-07-11

Клиент подключает платформы сам в UI (без .env). Ресурс продвижения расширяется полями
подключения: ``app_id``, ``app_secret_encrypted``/``app_secret_masked`` (секрет — только
зашифрованно/маской), ``status``, результат последней проверки (``last_check_*``) и
``resource_metadata`` (несекретные параметры: redirect_uri и т. п.). Основной токен
площадки хранится в существующем ``api_key_encrypted``. Совместимо со SQLite/PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018_platform_connection_fields"
down_revision: str | None = "0017_payment_webhook_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.add_column("crm_smm_resources", sa.Column("app_id", sa.String(length=255), nullable=True))
    op.add_column("crm_smm_resources", sa.Column("app_secret_encrypted", sa.Text(), nullable=True))
    op.add_column(
        "crm_smm_resources", sa.Column("app_secret_masked", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "crm_smm_resources",
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
    )
    op.add_column(
        "crm_smm_resources",
        sa.Column("last_check_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "crm_smm_resources", sa.Column("last_check_status", sa.String(length=20), nullable=True)
    )
    op.add_column(
        "crm_smm_resources", sa.Column("last_check_message", sa.String(length=1000), nullable=True)
    )
    op.add_column(
        "crm_smm_resources",
        sa.Column("resource_metadata", _json(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_crm_smm_resources_status", "crm_smm_resources", ["status"])


def downgrade() -> None:
    op.drop_index("ix_crm_smm_resources_status", table_name="crm_smm_resources")
    op.drop_column("crm_smm_resources", "resource_metadata")
    op.drop_column("crm_smm_resources", "last_check_message")
    op.drop_column("crm_smm_resources", "last_check_status")
    op.drop_column("crm_smm_resources", "last_check_at")
    op.drop_column("crm_smm_resources", "status")
    op.drop_column("crm_smm_resources", "app_secret_masked")
    op.drop_column("crm_smm_resources", "app_secret_encrypted")
    op.drop_column("crm_smm_resources", "app_id")
