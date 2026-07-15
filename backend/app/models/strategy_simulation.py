"""Стратегическая симуляция (v0.7.5) — вход AI Strategy Simulator.

Simulator берёт сценарий решения (Decision Engine) и моделирует его последствия на горизонте
30/60/90 дней: строит прогноз метрик, оценивает уверенность, сравнивает сценарии и показывает
ожидаемый результат. Это аналитический слой.

Поток: **Decision Scenario → Simulation → Forecast → Comparison → Recommendation**.

БЕЗОПАСНОСТЬ:
- строго per-project; секретов/токенов НЕТ; НЕ гарантирует прибыль, НЕ меняет
  бизнес/CRM/бюджет/live/публикации, НЕ выполняет стратегии — только моделирует и советует.
"""

from typing import Any

from sqlalchemy import Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины AI Strategy Simulator (Часть 1) ---

# Горизонты прогноза.
FORECAST_PERIODS: tuple[str, ...] = ("30_days", "60_days", "90_days", "custom")
# Метрики прогноза.
FORECAST_METRICS: tuple[str, ...] = (
    "revenue",
    "leads",
    "conversion",
    "traffic",
    "engagement",
    "efficiency",
)
# Статусы симуляции.
SIMULATION_STATUSES: tuple[str, ...] = ("generated", "running", "completed", "reviewed")
# Уровни уверенности.
CONFIDENCE_LEVELS: tuple[str, ...] = ("low", "medium", "high")


class StrategySimulation(Base, TimestampMixin):
    """Одна стратегическая симуляция сценария (per-project, без секретов)."""

    __tablename__ = "strategy_simulations"
    __table_args__ = (Index("ix_strategy_simulations_project_status", "project_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    decision_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_decisions.id", ondelete="SET NULL"), index=True, default=None
    )
    scenario_id: Mapped[int] = mapped_column(
        ForeignKey("decision_scenarios.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # generated | running | completed | reviewed
    status: Mapped[str] = mapped_column(String(20), default="generated", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    objective: Mapped[str | None] = mapped_column(Text, default=None)
    assumptions: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    # 30_days | 60_days | 90_days | custom
    simulation_period: Mapped[str] = mapped_column(String(20), default="90_days", nullable=False)
    # low | medium | high
    confidence_level: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    overall_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
