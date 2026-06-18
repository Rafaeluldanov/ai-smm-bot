"""Модель действия согласования поста (журнал ревью).

Каждая запись фиксирует одно действие над постом в процессе согласования:
отправку на ревью, одобрение, отклонение, запрос доработки, возврат в черновик,
ручную правку текста/медиа или комментарий. Это журнал (audit log) — записи не
изменяются и не удаляются, по ним строится таймлайн поста.
"""

from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class PostReviewAction(Base, TimestampMixin):
    """Одно действие согласования над постом."""

    __tablename__ = "post_review_actions"
    __table_args__ = (Index("ix_post_review_actions_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # Действие: "submit_for_review" | "approve" | "reject" | "request_changes" |
    # "return_to_draft" | "edit_text" | "change_media" | "comment".
    action: Mapped[str] = mapped_column(String(50), index=True, nullable=False)

    from_status: Mapped[str | None] = mapped_column(String(50), default=None)
    to_status: Mapped[str | None] = mapped_column(String(50), default=None)

    comment: Mapped[str | None] = mapped_column(Text, default=None)
    actor_name: Mapped[str | None] = mapped_column(String(255), default=None)
    actor_role: Mapped[str | None] = mapped_column(String(50), default=None)

    # Детали действия: какие поля изменены, версии текста до/после, причина и т. п.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
