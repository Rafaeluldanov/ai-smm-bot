"""AI-решение (v0.7.4) — вход AI Decision Engine.

Decision Engine выявляет бизнес-проблему, строит варианты решений (сценарии), оценивает и
сравнивает их эффект/риск и рекомендует лучший. Это аналитический и рекомендательный слой.

Поток: **Problem → Decision Options → Scenario Analysis → AI Recommendation → Owner Approval**.

БЕЗОПАСНОСТЬ:
- строго per-project; секретов/токенов НЕТ; НЕ применяет решения автоматически и НЕ меняет
  бизнес/CRM/бюджет/live/публикации — apply лишь создаёт ЧЕРНОВИК процесса (draft workflow)
  при status=accepted И подтверждении APPLY_DECISION.
"""

from typing import Any

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины AI Decision Engine (Часть 1) ---

# Типы решений.
DECISION_TYPES: tuple[str, ...] = (
    "growth",
    "revenue",
    "marketing",
    "sales",
    "content",
    "efficiency",
    "operational",
)
# Статусы решения.
DECISION_STATUSES: tuple[str, ...] = (
    "draft",
    "analyzing",
    "reviewed",
    "recommended",
    "accepted",
    "rejected",
    "applied",
)
# Статусы сценария.
SCENARIO_STATUSES: tuple[str, ...] = ("generated", "evaluated", "selected", "rejected")
# Приоритеты решения.
DECISION_PRIORITIES: tuple[str, ...] = ("critical", "high", "medium", "low")


class AIDecision(Base, TimestampMixin):
    """Одно AI-решение проекта (per-project, без секретов)."""

    __tablename__ = "ai_decisions"
    __table_args__ = (
        Index("ix_ai_decisions_project_status", "project_id", "status"),
        Index("ix_ai_decisions_account", "account_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # growth | revenue | marketing | sales | content | efficiency | operational
    decision_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # draft | analyzing | reviewed | recommended | accepted | rejected | applied
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    # critical | high | medium | low
    priority: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    problem_statement: Mapped[str | None] = mapped_column(Text, default=None)
    objective: Mapped[str | None] = mapped_column(Text, default=None)
    context: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    # id выбранного/рекомендованного сценария (мягкая ссылка, без FK — избегаем цикла FK).
    recommended_scenario_id: Mapped[int | None] = mapped_column(Integer, default=None)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
