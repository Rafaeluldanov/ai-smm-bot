"""Эксперимент оптимизации (v0.8.1) — проверка гипотезы улучшения.

Формализует проверку одного улучшения: гипотеза, метрика, базовое и целевое значения, окно
измерения, статус. Только план измерения — эксперимент НЕ запускается автоматически и НИЧЕГО не
меняет в бизнесе.

БЕЗОПАСНОСТЬ:
- эксперимент — только гипотеза/измерение; НЕ выполняет действий; секретов не содержит.
"""

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class OptimizationExperiment(Base, TimestampMixin):
    """Эксперимент проверки улучшения (per-optimization, без секретов)."""

    __tablename__ = "optimization_experiments"

    id: Mapped[int] = mapped_column(primary_key=True)
    optimization_id: Mapped[int] = mapped_column(
        ForeignKey("optimization_items.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    hypothesis: Mapped[str | None] = mapped_column(Text, default=None)
    # Метрика проверки (напр. execution_speed, conversion, revenue).
    metric: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    baseline_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    target_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # draft | approved | running | completed | failed
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    # Окно измерения в днях.
    measurement_period: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
