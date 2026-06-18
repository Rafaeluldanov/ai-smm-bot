"""Модель автономного прогона (Этап 10).

Один прогон = одна попытка автономно подготовить работу SMM-менеджера по проекту:
выбрать темы, сгенерировать посты, подобрать медиа, отправить на согласование и
(при разрешении) запланировать/опубликовать. Реальные публикации и AI на этом
этапе не выполняются без явных настроек; сеть в прогоне не вызывается.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class AutonomousRun(Base, TimestampMixin):
    """Автономный прогон pipeline по проекту."""

    __tablename__ = "autonomous_runs"
    __table_args__ = (Index("ix_autonomous_runs_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # Режим: "dry_run" | "semi_auto" | "auto_generate" | "auto_schedule" | "auto_publish".
    mode: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    # Статус: "created" | "running" | "completed" | "completed_with_warnings" |
    # "failed" | "cancelled".
    status: Mapped[str] = mapped_column(String(40), default="created", index=True, nullable=False)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    weeks: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    posts_per_week: Mapped[int] = mapped_column(Integer, default=3, nullable=False)

    business_priorities: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
    settings: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    errors: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
