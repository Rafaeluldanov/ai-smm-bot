"""Content experiments (A/B testing + topic optimization) (v0.4.2)

Revision ID: 0024_content_experiments
Revises: 0023_metric_import_runs
Create Date: 2026-07-11

A/B-тестирование вариантов постов и оптимизация тем: эксперименты и их варианты (A/B/C).
Live-публикаций нет; варианты идут в очередь ревью. Секретов в metadata нет. Совместимо
со SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0024_content_experiments"
down_revision: str | None = "0023_metric_import_runs"
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
        "content_experiments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("platform_key", sa.String(length=40), nullable=True),
        sa.Column(
            "experiment_type", sa.String(length=20), nullable=False, server_default="ab_test"
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("source_post_id", sa.Integer(), nullable=True),
        sa.Column("source_schedule_run_id", sa.Integer(), nullable=True),
        sa.Column("winner_variant_id", sa.Integer(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("learning_profile_version", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("experiment_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_post_id"], ["posts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["source_schedule_run_id"], ["schedule_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_content_experiments_account_id", "content_experiments", ["account_id"])
    op.create_index("ix_content_experiments_project_id", "content_experiments", ["project_id"])
    op.create_index("ix_content_experiments_platform_key", "content_experiments", ["platform_key"])
    op.create_index("ix_content_experiments_status", "content_experiments", ["status"])
    op.create_index(
        "ix_content_experiments_experiment_type", "content_experiments", ["experiment_type"]
    )
    op.create_index(
        "ix_content_experiments_source_post_id", "content_experiments", ["source_post_id"]
    )
    op.create_index(
        "ix_content_experiments_created_by_user_id", "content_experiments", ["created_by_user_id"]
    )

    op.create_table(
        "content_experiment_variants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("experiment_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=True),
        sa.Column("publication_id", sa.Integer(), nullable=True),
        sa.Column("variant_key", sa.String(length=4), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("angle", sa.String(length=64), nullable=True),
        sa.Column("cta_type", sa.String(length=64), nullable=True),
        sa.Column("text_length_type", sa.String(length=32), nullable=True),
        sa.Column("media_strategy", sa.String(length=64), nullable=True),
        sa.Column("publish_time_strategy", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("quality_score", sa.Integer(), nullable=True),
        sa.Column("predicted_engagement_score", sa.Integer(), nullable=True),
        sa.Column("actual_engagement_score", sa.Integer(), nullable=True),
        sa.Column("er_percent", sa.Float(), nullable=True),
        sa.Column("ctr_percent", sa.Float(), nullable=True),
        sa.Column("score_breakdown", _json(), nullable=False, server_default="{}"),
        sa.Column("learning_reasons", _json(), nullable=False, server_default="[]"),
        sa.Column("metrics_snapshot", _json(), nullable=False, server_default="{}"),
        sa.Column("is_winner", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("winner_reason", sa.String(length=40), nullable=True),
        sa.Column("variant_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["experiment_id"], ["content_experiments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["publication_id"], ["post_publications.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_content_experiment_variants_experiment_id",
        "content_experiment_variants",
        ["experiment_id"],
    )
    op.create_index(
        "ix_content_experiment_variants_account_id",
        "content_experiment_variants",
        ["account_id"],
    )
    op.create_index(
        "ix_content_experiment_variants_project_id",
        "content_experiment_variants",
        ["project_id"],
    )
    op.create_index(
        "ix_content_experiment_variants_post_id", "content_experiment_variants", ["post_id"]
    )
    op.create_index(
        "ix_content_experiment_variants_publication_id",
        "content_experiment_variants",
        ["publication_id"],
    )
    op.create_index(
        "ix_content_experiment_variants_status", "content_experiment_variants", ["status"]
    )
    op.create_index(
        "ix_content_experiment_variants_is_winner",
        "content_experiment_variants",
        ["is_winner"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_content_experiment_variants_is_winner", table_name="content_experiment_variants"
    )
    op.drop_index("ix_content_experiment_variants_status", table_name="content_experiment_variants")
    op.drop_index(
        "ix_content_experiment_variants_publication_id",
        table_name="content_experiment_variants",
    )
    op.drop_index(
        "ix_content_experiment_variants_post_id", table_name="content_experiment_variants"
    )
    op.drop_index(
        "ix_content_experiment_variants_project_id", table_name="content_experiment_variants"
    )
    op.drop_index(
        "ix_content_experiment_variants_account_id", table_name="content_experiment_variants"
    )
    op.drop_index(
        "ix_content_experiment_variants_experiment_id",
        table_name="content_experiment_variants",
    )
    op.drop_table("content_experiment_variants")

    op.drop_index("ix_content_experiments_created_by_user_id", table_name="content_experiments")
    op.drop_index("ix_content_experiments_source_post_id", table_name="content_experiments")
    op.drop_index("ix_content_experiments_experiment_type", table_name="content_experiments")
    op.drop_index("ix_content_experiments_status", table_name="content_experiments")
    op.drop_index("ix_content_experiments_platform_key", table_name="content_experiments")
    op.drop_index("ix_content_experiments_project_id", table_name="content_experiments")
    op.drop_index("ix_content_experiments_account_id", table_name="content_experiments")
    op.drop_table("content_experiments")
