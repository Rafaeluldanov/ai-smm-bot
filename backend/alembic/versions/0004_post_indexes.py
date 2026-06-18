"""posts: index on status

Revision ID: 0004_post_indexes
Revises: 0003_topic_unique_project_title
Create Date: 2026-06-18

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_post_indexes"
down_revision: str | None = "0003_topic_unique_project_title"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Индексы project_id/topic_id/media_asset_id уже созданы в 0001.
    # Здесь добавляем индекс по статусу — частый фильтр в выборках постов.
    op.create_index("ix_posts_status", "posts", ["status"])


def downgrade() -> None:
    op.drop_index("ix_posts_status", table_name="posts")
