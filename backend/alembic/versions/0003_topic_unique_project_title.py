"""topics: unique index (project_id, title) + status/cluster indexes

Revision ID: 0003_topic_unique_project_title
Revises: 0002_media_asset_disk_path_indexes
Create Date: 2026-06-18

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_topic_unique_project_title"
down_revision: str | None = "0002_media_asset_disk_path_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_topics_status", "topics", ["status"])
    op.create_index("ix_topics_cluster", "topics", ["cluster"])
    # Бизнес-уникальность темы в рамках проекта (anti-duplicate при upsert).
    op.create_index(
        "ix_topics_project_id_title",
        "topics",
        ["project_id", "title"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_topics_project_id_title", table_name="topics")
    op.drop_index("ix_topics_cluster", table_name="topics")
    op.drop_index("ix_topics_status", table_name="topics")
