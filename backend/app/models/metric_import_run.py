"""Модель прогона импорта метрик (metric import run) — v0.4.1.

Один запуск импорта метрик постов проекта из источника (demo / manual / estimated /
internal / api). Фиксирует, что бот собрал: сколько публикаций просканировано, сколько
снимков создано, сколько сигналов обучения записано и сколько units списано.

БЕЗОПАСНОСТЬ:
- ``import_metadata`` НЕ содержит секретов/токенов (обеспечивает сервисный слой);
- реальные внешние API по умолчанию выключены (feature flag); demo/manual — без сети.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class MetricImportRun(Base, TimestampMixin):
    """Один прогон импорта метрик (project × platform × source × period)."""

    __tablename__ = "metric_import_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # None → все площадки проекта; иначе — конкретная.
    platform_key: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    # internal | manual | estimated | api | demo
    source: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    # preview | pending | imported | partially_imported | failed | skipped |
    # no_credentials | live_disabled
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True, nullable=False)
    # Период выборки публикаций (YYYY-MM-DD), опционально.
    period_start: Mapped[str | None] = mapped_column(String(20), default=None)
    period_end: Mapped[str | None] = mapped_column(String(20), default=None)

    publications_scanned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metrics_imported: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    snapshots_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    learning_events_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    units_estimated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    units_charged: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Идемпотентность прогона (nullable: preview/dry-run без ключа).
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True, default=None
    )
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    import_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
