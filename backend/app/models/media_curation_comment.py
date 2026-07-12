"""Модель комментария к задаче курирования медиатеки (collaborative review) — v0.4.9.

Комментарии — часть workflow согласования медиатеки: обсуждение, решения (approve/reject/
request_changes) и системные события. В MVP комментарии физически НЕ удаляются.

БЕЗОПАСНОСТЬ:
- ``comment_text``/``comment_metadata`` санитизируются на сервисном слое (без секретов и
  внутренних путей к файлам);
- строго account/project-scoped (изоляция — на API/сервисном слое).
"""

from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class MediaCurationComment(Base, TimestampMixin):
    """Комментарий/решение/системное событие по задаче курирования (без физического удаления)."""

    __tablename__ = "media_curation_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    task_id: Mapped[int] = mapped_column(
        ForeignKey("media_curation_tasks.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )

    comment_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    comment_type: Mapped[str] = mapped_column(
        String(30), index=True, default="comment", nullable=False
    )
    comment_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
