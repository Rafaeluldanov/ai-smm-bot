"""media_assets: unique index on yandex_disk_path + status/source_type indexes

Revision ID: 0002_media_asset_idx
Revises: 0001_initial
Create Date: 2026-06-18

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_media_asset_idx"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Бизнес-уникальность файла на Яндекс Диске (anti-duplicate при синхронизации).
    op.create_index(
        "ix_media_assets_yandex_disk_path",
        "media_assets",
        ["yandex_disk_path"],
        unique=True,
    )
    op.create_index("ix_media_assets_status", "media_assets", ["status"])
    op.create_index("ix_media_assets_source_type", "media_assets", ["source_type"])


def downgrade() -> None:
    op.drop_index("ix_media_assets_source_type", table_name="media_assets")
    op.drop_index("ix_media_assets_status", table_name="media_assets")
    op.drop_index("ix_media_assets_yandex_disk_path", table_name="media_assets")
