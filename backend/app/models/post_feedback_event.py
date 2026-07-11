"""Событие обратной связи по посту (v0.4.0) — сигнал для обучения бота.

Каждое решение клиента (одобрил / отклонил / запросил правки / отредактировал /
опубликовал / поставил оценку) и импорт аналитики фиксируются как ``PostFeedbackEvent``.
На основе потока событий строится :class:`ClientLearningProfile`.

БЕЗОПАСНОСТЬ:
- секреты/токены НЕ хранятся; ``event_metadata`` санитизируется на уровне сервиса;
- полный текст поста НЕ хранится — только ``before_text_hash`` / ``after_text_hash`` и
  агрегированный ``diff_summary`` (что именно поменяли).
"""

from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class PostFeedbackEvent(Base, TimestampMixin):
    """Одно событие обратной связи/сигнала по посту."""

    __tablename__ = "post_feedback_events"
    __table_args__ = (
        Index("ix_post_feedback_events_project_platform", "project_id", "platform_key"),
        Index("ix_post_feedback_events_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    publication_id: Mapped[int | None] = mapped_column(
        ForeignKey("post_publications.id", ondelete="SET NULL"), index=True, default=None
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )
    platform_key: Mapped[str | None] = mapped_column(String(40), default=None)
    # approved | rejected | changes_requested | edited | published |
    # manual_rating | analytics_imported | auto_published | auto_blocked
    event_type: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    rating: Mapped[int | None] = mapped_column(Integer, default=None)  # 1..5, опционально
    reason_tags: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    before_text_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    after_text_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    diff_summary: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    metrics_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
