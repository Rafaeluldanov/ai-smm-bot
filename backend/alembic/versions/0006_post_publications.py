"""post_publications: публикации поста по платформам

Revision ID: 0006_post_publications
Revises: 0005_post_review_actions
Create Date: 2026-06-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_post_publications"
down_revision: str | None = "0005_post_review_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "post_publications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("external_post_id", sa.String(length=255), nullable=True),
        sa.Column("external_url", sa.String(length=1024), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_post_publications_post_id", "post_publications", ["post_id"])
    op.create_index("ix_post_publications_project_id", "post_publications", ["project_id"])
    op.create_index("ix_post_publications_platform", "post_publications", ["platform"])
    op.create_index("ix_post_publications_status", "post_publications", ["status"])
    op.create_index("ix_post_publications_scheduled_at", "post_publications", ["scheduled_at"])
    op.create_index("ix_post_publications_published_at", "post_publications", ["published_at"])
    # Идемпотентность: один пост — одна публикация на платформу.
    op.create_index(
        "ix_post_publications_post_id_platform",
        "post_publications",
        ["post_id", "platform"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("post_publications")
