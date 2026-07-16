"""AI Optimization Governance: governance + owner assignments + impacts + reviews (v0.8.2)

Revision ID: 0064_ai_optimization_governance
Revises: 0063_ai_autonomous_optimization
Create Date: 2026-07-16

Governance-слой: управление портфелем улучшений. Optimization Item → Governance Review → Approval →
Ownership → Impact Tracking. Секретов не хранит; НЕ применяет улучшения, НЕ запускает эксперименты,
НЕ меняет бизнес/KPI/CRM/бюджет, НЕ выполняет задачи. SQLite+PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic (<=32 chars: alembic_version.version_num is varchar(32)).
revision: str = "0064_ai_optimization_governance"
down_revision: str | None = "0063_ai_autonomous_optimization"
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
        "optimization_governances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("optimization_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="identified"),
        sa.Column(
            "approval_status", sa.String(length=20), nullable=False, server_default="pending"
        ),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["optimization_id"], ["optimization_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_optimization_governances_account_id", "optimization_governances", ["account_id"]
    )
    op.create_index(
        "ix_optimization_governances_project_id", "optimization_governances", ["project_id"]
    )
    op.create_index(
        "ix_optimization_governances_optimization_id",
        "optimization_governances",
        ["optimization_id"],
    )
    op.create_index(
        "ix_optimization_governances_owner_user_id", "optimization_governances", ["owner_user_id"]
    )
    op.create_index(
        "ix_optimization_governances_project_status",
        "optimization_governances",
        ["project_id", "status"],
    )

    op.create_table(
        "optimization_owner_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("governance_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("role", sa.String(length=30), nullable=False, server_default="owner"),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["governance_id"], ["optimization_governances.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_optimization_owner_assignments_governance_id",
        "optimization_owner_assignments",
        ["governance_id"],
    )
    op.create_index(
        "ix_optimization_owner_assignments_owner_user_id",
        "optimization_owner_assignments",
        ["owner_user_id"],
    )

    op.create_table(
        "optimization_impacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("governance_id", sa.Integer(), nullable=False),
        sa.Column("experiment_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="unknown"),
        sa.Column("expected_impact", _json(), nullable=False, server_default="{}"),
        sa.Column("actual_impact", _json(), nullable=False, server_default="{}"),
        sa.Column("impact_score", sa.Float(), nullable=False, server_default="0"),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["governance_id"], ["optimization_governances.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["experiment_id"], ["optimization_experiments.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_optimization_impacts_governance_id", "optimization_impacts", ["governance_id"]
    )
    op.create_index(
        "ix_optimization_impacts_experiment_id", "optimization_impacts", ["experiment_id"]
    )

    op.create_table(
        "governance_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("governance_id", sa.Integer(), nullable=False),
        sa.Column("reviewer_user_id", sa.Integer(), nullable=True),
        sa.Column("decision", sa.String(length=20), nullable=False, server_default="comment"),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["governance_id"], ["optimization_governances.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_governance_reviews_governance_id", "governance_reviews", ["governance_id"])
    op.create_index(
        "ix_governance_reviews_reviewer_user_id", "governance_reviews", ["reviewer_user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_governance_reviews_reviewer_user_id", table_name="governance_reviews")
    op.drop_index("ix_governance_reviews_governance_id", table_name="governance_reviews")
    op.drop_table("governance_reviews")

    op.drop_index("ix_optimization_impacts_experiment_id", table_name="optimization_impacts")
    op.drop_index("ix_optimization_impacts_governance_id", table_name="optimization_impacts")
    op.drop_table("optimization_impacts")

    op.drop_index(
        "ix_optimization_owner_assignments_owner_user_id",
        table_name="optimization_owner_assignments",
    )
    op.drop_index(
        "ix_optimization_owner_assignments_governance_id",
        table_name="optimization_owner_assignments",
    )
    op.drop_table("optimization_owner_assignments")

    op.drop_index(
        "ix_optimization_governances_project_status", table_name="optimization_governances"
    )
    op.drop_index(
        "ix_optimization_governances_owner_user_id", table_name="optimization_governances"
    )
    op.drop_index(
        "ix_optimization_governances_optimization_id", table_name="optimization_governances"
    )
    op.drop_index("ix_optimization_governances_project_id", table_name="optimization_governances")
    op.drop_index("ix_optimization_governances_account_id", table_name="optimization_governances")
    op.drop_table("optimization_governances")
