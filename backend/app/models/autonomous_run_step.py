"""Модель шага автономного прогона (Этап 10).

Журнал шагов pipeline: что делалось, с какой сущностью, входные/выходные данные,
предупреждения и ошибки. По шагам строится отчёт прогона.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class AutonomousRunStep(Base, TimestampMixin):
    """Один шаг автономного прогона (audit-запись)."""

    __tablename__ = "autonomous_run_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("autonomous_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # Имя шага: select_topics | build_content_plan | generate_posts | select_media |
    # search_external_images | submit_for_review | schedule_posts | publish_posts |
    # collect_analytics | build_report.
    step_name: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    # Статус шага: "pending" | "running" | "completed" | "skipped" | "failed".
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True, nullable=False)

    entity_type: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    entity_id: Mapped[int | None] = mapped_column(Integer, index=True, default=None)

    input_payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    output_payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    errors: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
