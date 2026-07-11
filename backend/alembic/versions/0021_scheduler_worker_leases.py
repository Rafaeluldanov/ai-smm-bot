"""Scheduler worker leases: DB-based lock фонового worker-а

Revision ID: 0021_scheduler_worker_leases
Revises: 0020_schedule_runs
Create Date: 2026-07-11

Простой DB-lock, чтобы работал один фоновый worker. Если процесс умер — lease истекает
по TTL и может быть перехвачен. Без Redis/Celery на MVP. Секретов в metadata нет.
Совместимо со SQLite (тесты) и PostgreSQL (JSONB variant).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0021_scheduler_worker_leases"
down_revision: str | None = "0020_schedule_runs"
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
        "scheduler_worker_leases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lease_key", sa.String(length=100), nullable=False),
        sa.Column("owner_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_scheduler_worker_leases_lease_key",
        "scheduler_worker_leases",
        ["lease_key"],
        unique=True,
    )
    op.create_index("ix_scheduler_worker_leases_status", "scheduler_worker_leases", ["status"])
    op.create_index(
        "ix_scheduler_worker_leases_expires_at", "scheduler_worker_leases", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_scheduler_worker_leases_expires_at", table_name="scheduler_worker_leases")
    op.drop_index("ix_scheduler_worker_leases_status", table_name="scheduler_worker_leases")
    op.drop_index("ix_scheduler_worker_leases_lease_key", table_name="scheduler_worker_leases")
    op.drop_table("scheduler_worker_leases")
