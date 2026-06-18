"""post_analytics_snapshots: снимки аналитики публикаций

Revision ID: 0007_post_analytics_snapshots
Revises: 0006_post_publications
Create Date: 2026-06-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_post_analytics_snapshots"
down_revision: str | None = "0006_post_publications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "post_analytics_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("post_publication_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("topic_id", sa.Integer(), nullable=True),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column(
            "snapshot_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("impressions", sa.Integer(), nullable=False),
        sa.Column("reach", sa.Integer(), nullable=False),
        sa.Column("views", sa.Integer(), nullable=False),
        sa.Column("likes", sa.Integer(), nullable=False),
        sa.Column("reactions", sa.Integer(), nullable=False),
        sa.Column("comments", sa.Integer(), nullable=False),
        sa.Column("shares", sa.Integer(), nullable=False),
        sa.Column("saves", sa.Integer(), nullable=False),
        sa.Column("clicks", sa.Integer(), nullable=False),
        sa.Column("ctr", sa.Float(), nullable=False),
        sa.Column("engagement_rate", sa.Float(), nullable=False),
        sa.Column("raw_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
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
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["post_publication_id"], ["post_publications.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_post_analytics_snapshots_post_id", "post_analytics_snapshots", ["post_id"])
    op.create_index(
        "ix_post_analytics_snapshots_post_publication_id",
        "post_analytics_snapshots",
        ["post_publication_id"],
    )
    op.create_index(
        "ix_post_analytics_snapshots_project_id", "post_analytics_snapshots", ["project_id"]
    )
    op.create_index(
        "ix_post_analytics_snapshots_topic_id", "post_analytics_snapshots", ["topic_id"]
    )
    op.create_index(
        "ix_post_analytics_snapshots_platform", "post_analytics_snapshots", ["platform"]
    )
    op.create_index(
        "ix_post_analytics_snapshots_snapshot_at", "post_analytics_snapshots", ["snapshot_at"]
    )
    op.create_index("ix_post_analytics_snapshots_source", "post_analytics_snapshots", ["source"])


def downgrade() -> None:
    op.drop_table("post_analytics_snapshots")
