"""Прогноз развития бизнеса (v0.7.6) — вход AI Business Forecasting Engine.

Engine берёт текущее состояние бизнеса (Operations/Strategy Simulator/Decision Engine) и
прогнозирует развитие на 3/6/12 месяцев: проекция KPI, поправка на риск, бизнес-outlook.
Это аналитический прогнозный слой.

Поток: **Business State → Forecast Model → KPI Projection → Risk Adjustment → Business
Outlook → Owner Review**.

БЕЗОПАСНОСТЬ:
- строго per-project; секретов/токенов НЕТ; НЕ гарантирует прибыль, НЕ обещает финансовый
  результат, НЕ меняет бизнес/CRM/бюджет, НЕ выполняет стратегии, НЕ ходит во внешние API —
  только прогнозирует и советует.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины AI Business Forecasting Engine (Часть 1) ---

# Горизонты прогноза.
FORECAST_HORIZONS: tuple[str, ...] = ("3_months", "6_months", "12_months")
# Статусы прогноза.
FORECAST_STATUSES: tuple[str, ...] = ("generated", "reviewed", "archived")
# Бизнес-метрики.
BUSINESS_METRICS: tuple[str, ...] = (
    "revenue",
    "leads",
    "customers",
    "conversion",
    "traffic",
    "efficiency",
)
# Уровни риска.
RISK_LEVELS: tuple[str, ...] = ("low", "medium", "high", "critical")


class BusinessForecast(Base, TimestampMixin):
    """Один прогноз развития бизнеса на горизонт (per-project, без секретов)."""

    __tablename__ = "business_forecasts"
    __table_args__ = (Index("ix_business_forecasts_project_status", "project_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # generated | reviewed | archived
    status: Mapped[str] = mapped_column(String(20), default="generated", nullable=False)
    # 3_months | 6_months | 12_months
    horizon: Mapped[str] = mapped_column(String(20), default="12_months", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    baseline_state: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    forecast_state: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    assumptions: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    # low | medium | high | critical
    risk_level: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
