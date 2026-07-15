"""AI Operations Control Center: snapshots + risks + recommendations (v0.7.3)

Revision ID: 0055_ai_operations_control_center
Revises: 0054_ai_workflow_manager
Create Date: 2026-07-15

Единая операционная панель (Operations Control Center): снапшоты состояния + риски +
рекомендации (Collect Signals → Calculate Health → Detect Risks → Recommend → Owner Review).
Секретов не хранит; НЕ выполняет действий, НЕ меняет CRM/бюджет/продажи/live/публикации.
Совместимо со SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic (<=32 chars: alembic_version.version_num is varchar(32)).
revision: str = "0055_ai_operations_center"
down_revision: str | None = "0054_ai_workflow_manager"
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
        "operations_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("health_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="healthy"),
        sa.Column("metrics", _json(), nullable=False, server_default="{}"),
        sa.Column("business_state", _json(), nullable=False, server_default="{}"),
        sa.Column("growth_state", _json(), nullable=False, server_default="{}"),
        sa.Column("sales_state", _json(), nullable=False, server_default="{}"),
        sa.Column("workflow_state", _json(), nullable=False, server_default="{}"),
        sa.Column("risk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_operations_snapshots_account_id", "operations_snapshots", ["account_id"])
    op.create_index("ix_operations_snapshots_project_id", "operations_snapshots", ["project_id"])
    op.create_index("ix_operations_snapshots_account", "operations_snapshots", ["account_id"])
    op.create_index(
        "ix_operations_snapshots_project_created",
        "operations_snapshots",
        ["project_id", "created_at"],
    )

    op.create_table(
        "operations_risks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("risk_type", sa.String(length=20), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_module", sa.String(length=40), nullable=True),
        sa.Column("source_entity_id", sa.Integer(), nullable=True),
        sa.Column("impact", _json(), nullable=False, server_default="{}"),
        sa.Column("recommended_action", _json(), nullable=False, server_default="{}"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_operations_risks_account_id", "operations_risks", ["account_id"])
    op.create_index("ix_operations_risks_project_id", "operations_risks", ["project_id"])
    op.create_index("ix_operations_risks_account", "operations_risks", ["account_id"])
    op.create_index(
        "ix_operations_risks_project_status", "operations_risks", ["project_id", "status"]
    )

    op.create_table(
        "operations_recommendations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("reasoning", _json(), nullable=False, server_default="[]"),
        sa.Column("source_signals", _json(), nullable=False, server_default="[]"),
        sa.Column("expected_impact", _json(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="generated"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_operations_recommendations_account_id", "operations_recommendations", ["account_id"]
    )
    op.create_index(
        "ix_operations_recommendations_project_id", "operations_recommendations", ["project_id"]
    )
    op.create_index(
        "ix_operations_recommendations_account", "operations_recommendations", ["account_id"]
    )
    op.create_index(
        "ix_operations_recommendations_project_status",
        "operations_recommendations",
        ["project_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_operations_recommendations_project_status", table_name="operations_recommendations"
    )
    op.drop_index("ix_operations_recommendations_account", table_name="operations_recommendations")
    op.drop_index(
        "ix_operations_recommendations_project_id", table_name="operations_recommendations"
    )
    op.drop_index(
        "ix_operations_recommendations_account_id", table_name="operations_recommendations"
    )
    op.drop_table("operations_recommendations")

    op.drop_index("ix_operations_risks_project_status", table_name="operations_risks")
    op.drop_index("ix_operations_risks_account", table_name="operations_risks")
    op.drop_index("ix_operations_risks_project_id", table_name="operations_risks")
    op.drop_index("ix_operations_risks_account_id", table_name="operations_risks")
    op.drop_table("operations_risks")

    op.drop_index("ix_operations_snapshots_project_created", table_name="operations_snapshots")
    op.drop_index("ix_operations_snapshots_account", table_name="operations_snapshots")
    op.drop_index("ix_operations_snapshots_project_id", table_name="operations_snapshots")
    op.drop_index("ix_operations_snapshots_account_id", table_name="operations_snapshots")
    op.drop_table("operations_snapshots")
