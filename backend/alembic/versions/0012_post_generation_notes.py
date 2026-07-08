"""posts: generation_notes JSON column (media group posts)

Revision ID: 0012_post_generation_notes
Revises: 0011_crm_bot_smm_configurator
Create Date: 2026-07-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012_post_generation_notes"
down_revision: str | None = "0011_crm_bot_smm_configurator"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json() -> sa.types.TypeEngine:
    """JSON-тип: JSONB на PostgreSQL, JSON на прочих СУБД."""
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    # Технические заметки генерации поста (в т. ч. группа медиа для VK).
    op.add_column(
        "posts",
        sa.Column(
            "generation_notes",
            _json(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    # server_default нужен только для заполнения существующих строк при миграции;
    # дальше значение задаёт приложение (модель: default=dict).
    op.alter_column("posts", "generation_notes", server_default=None)


def downgrade() -> None:
    op.drop_column("posts", "generation_notes")
