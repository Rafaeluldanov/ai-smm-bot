"""autonomous_runs + autonomous_run_steps: автономный режим

Revision ID: 0009_autonomous_runs
Revises: 0008_external_image_candidates
Create Date: 2026-06-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_autonomous_runs"
down_revision: str | None = "0008_external_image_candidates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "autonomous_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("weeks", sa.Integer(), nullable=False),
        sa.Column("posts_per_week", sa.Integer(), nullable=False),
        sa.Column("business_priorities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("errors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_autonomous_runs_project_id", "autonomous_runs", ["project_id"])
    op.create_index("ix_autonomous_runs_mode", "autonomous_runs", ["mode"])
    op.create_index("ix_autonomous_runs_status", "autonomous_runs", ["status"])
    op.create_index("ix_autonomous_runs_created_at", "autonomous_runs", ["created_at"])

    op.create_table(
        "autonomous_run_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("step_name", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=True),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("input_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("errors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["run_id"], ["autonomous_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_autonomous_run_steps_run_id", "autonomous_run_steps", ["run_id"])
    op.create_index("ix_autonomous_run_steps_step_name", "autonomous_run_steps", ["step_name"])
    op.create_index("ix_autonomous_run_steps_status", "autonomous_run_steps", ["status"])
    op.create_index("ix_autonomous_run_steps_entity_type", "autonomous_run_steps", ["entity_type"])
    op.create_index("ix_autonomous_run_steps_entity_id", "autonomous_run_steps", ["entity_id"])


def downgrade() -> None:
    op.drop_table("autonomous_run_steps")
    op.drop_table("autonomous_runs")
