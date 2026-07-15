"""Операционный снапшот (v0.7.3) — вход AI Operations Control Center.

Единая операционная панель бизнеса: сводит состояние (рост, продажи, процессы,
исполнение) в один health-снапшот с рисками и рекомендациями. Это аналитический и
управленческий слой.

Поток: Collect Signals → Calculate Health → Detect Risks → Generate Recommendations → Owner Review.

БЕЗОПАСНОСТЬ:
- строго per-project; секретов/токенов НЕТ; НЕ выполняет действия и НЕ меняет
  CRM/бюджет/продажи/live/публикации — только собирает сигналы, считает и советует.
"""

from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины AI Operations Control Center (Часть 1) ---

# Типы операционных метрик.
OPERATIONS_METRIC_TYPES: tuple[str, ...] = (
    "revenue",
    "growth",
    "sales",
    "content",
    "workflow",
    "execution",
    "risk",
)
# Статусы операционного здоровья.
OPERATIONS_HEALTH_STATUSES: tuple[str, ...] = ("healthy", "warning", "critical")
# Типы операционных рисков.
OPERATIONS_RISK_TYPES: tuple[str, ...] = (
    "workflow_delay",
    "revenue_drop",
    "conversion_drop",
    "content_gap",
    "missing_data",
    "execution_block",
)
# Тяжесть риска.
OPERATIONS_RISK_SEVERITIES: tuple[str, ...] = ("low", "medium", "high", "critical")
# Статусы риска.
OPERATIONS_RISK_STATUSES: tuple[str, ...] = ("open", "resolved")
# Приоритеты рекомендации.
RECOMMENDATION_PRIORITIES: tuple[str, ...] = ("critical", "high", "medium", "low")
# Статусы рекомендации.
OPERATIONS_RECOMMENDATION_STATUSES: tuple[str, ...] = ("generated", "accepted", "rejected")


class OperationsSnapshot(Base, TimestampMixin):
    """Снимок операционного состояния проекта (per-project, без секретов)."""

    __tablename__ = "operations_snapshots"
    __table_args__ = (
        Index("ix_operations_snapshots_project_created", "project_id", "created_at"),
        Index("ix_operations_snapshots_account", "account_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    health_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # healthy | warning | critical
    status: Mapped[str] = mapped_column(String(20), default="healthy", nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    business_state: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    growth_state: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    sales_state: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    workflow_state: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    risk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    generated_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)
