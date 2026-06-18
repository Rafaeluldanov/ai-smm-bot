"""post_review_actions: журнал согласования постов

Revision ID: 0005_post_review_actions
Revises: 0004_post_indexes
Create Date: 2026-06-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_post_review_actions"
down_revision: str | None = "0004_post_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "post_review_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("from_status", sa.String(length=50), nullable=True),
        sa.Column("to_status", sa.String(length=50), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("actor_name", sa.String(length=255), nullable=True),
        sa.Column("actor_role", sa.String(length=50), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_post_review_actions_post_id", "post_review_actions", ["post_id"])
    op.create_index("ix_post_review_actions_action", "post_review_actions", ["action"])
    op.create_index("ix_post_review_actions_created_at", "post_review_actions", ["created_at"])


def downgrade() -> None:
    op.drop_table("post_review_actions")
