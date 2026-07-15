"""Бизнес-процесс (v0.7.2) — вход AI Workflow Manager / Business Execution Layer.

Workflow превращает бизнес-цель или AI-рекомендацию в управляемый процесс: цель, этапы,
ответственные, сроки, зависимости, прогресс, блокеры и рекомендации AI. Это слой
управления процессами (workflow management), НЕ исполнитель.

БЕЗОПАСНОСТЬ:
- строго per-project; секретов/токенов НЕТ; НЕ выполняет задачи и НЕ меняет
  CRM/бюджет/продажи/live/публикации — только Create → Steps → Assign → Track → Analyze → Recommend.
"""

from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины AI Workflow Manager (Часть 1) ---

# Типы процессов.
WORKFLOW_TYPES: tuple[str, ...] = (
    "growth",
    "marketing",
    "sales",
    "content",
    "operational",
    "custom",
)
# Статусы процесса.
WORKFLOW_STATUSES: tuple[str, ...] = ("draft", "active", "paused", "completed", "cancelled")
# Статусы этапа.
WORKFLOW_STEP_STATUSES: tuple[str, ...] = (
    "pending",
    "assigned",
    "in_progress",
    "blocked",
    "completed",
    "cancelled",
)
# Приоритеты этапа.
WORKFLOW_STEP_PRIORITIES: tuple[str, ...] = ("critical", "high", "medium", "low")
# Типы блокеров.
BLOCKER_TYPES: tuple[str, ...] = ("dependency", "resource", "approval", "missing_data", "external")
# Тяжесть блокера.
BLOCKER_SEVERITIES: tuple[str, ...] = ("low", "medium", "high", "critical")
# Статусы блокера.
BLOCKER_STATUSES: tuple[str, ...] = ("open", "resolved")

# Терминальные статусы процесса/этапа (не подлежат дальнейшим переходам).
WORKFLOW_TERMINAL_STATUSES: tuple[str, ...] = ("completed", "cancelled")
WORKFLOW_STEP_OPEN_STATUSES: tuple[str, ...] = (
    "pending",
    "assigned",
    "in_progress",
    "blocked",
)


class BusinessWorkflow(Base, TimestampMixin):
    """Бизнес-процесс проекта (per-project, без секретов)."""

    __tablename__ = "business_workflows"
    __table_args__ = (
        Index("ix_business_workflows_project_status", "project_id", "status"),
        Index("ix_business_workflows_account", "account_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    # growth | marketing | sales | content | operational | custom
    workflow_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # draft | active | paused | completed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    goal: Mapped[str | None] = mapped_column(Text, default=None)
    target_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    current_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    start_date: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)
    deadline: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)
    progress_percent: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    workflow_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
