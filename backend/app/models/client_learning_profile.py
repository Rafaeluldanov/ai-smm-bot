"""Профиль обучения бота на конкретном клиенте/проекте (v0.4.0).

Botfleet собирает сигналы обратной связи (что клиент одобряет / редактирует /
отклоняет + как посты работают по аналитике) и строит **персональный** профиль
проекта. Профиль используется при следующих генерациях и показывается клиенту в
блоке «Чему бот научился».

БЕЗОПАСНОСТЬ / ПРИВАТНОСТЬ:
- профиль строго per-project (и опционально per-platform); данные одного клиента
  НЕ смешиваются с другим и НЕ уходят в глобальное обучение модели;
- в профиле нет секретов/токенов — только агрегированные предпочтения и веса.
"""

from typing import Any

from sqlalchemy import Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class ClientLearningProfile(Base, TimestampMixin):
    """Персональный профиль обучения для (project × platform)."""

    __tablename__ = "client_learning_profiles"
    __table_args__ = (
        Index(
            "ix_client_learning_profiles_project_platform",
            "project_id",
            "platform_key",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # None → профиль всего проекта; иначе — по конкретной площадке.
    platform_key: Mapped[str | None] = mapped_column(String(40), default=None)
    profile_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # active | draft
    status: Mapped[str] = mapped_column(String(20), default="active", index=True, nullable=False)

    # --- Обученные предпочтения (JSON, без секретов) ---
    brand_voice: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    preferred_topics: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    rejected_topics: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    preferred_cta: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    rejected_cta: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    preferred_text_length: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
    preferred_media_types: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    high_performing_tags: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    low_performing_tags: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    best_publish_times: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)

    # --- Паттерны решений клиента (веса/счётчики) ---
    approval_patterns: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
    editing_patterns: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    performance_patterns: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
    forbidden_patterns: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    recommendations: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)

    # 0..1 — растёт с числом обработанных сигналов.
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    updated_from_events_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
