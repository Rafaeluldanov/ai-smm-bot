"""Зависимость задачи исполнения (v0.7.8) — «задача A зависит от B».

Фиксирует зависимость задачи от другой задачи/цели/внешнего фактора (для контроля порядка и
блокеров). Append-only.

БЕЗОПАСНОСТЬ:
- зависимость — только координационная связь; секретов не содержит.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExecutionDependency(Base):
    """Зависимость задачи исполнения (per-task, append-only, без секретов)."""

    __tablename__ = "execution_dependencies"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("execution_tasks.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # id задачи-зависимости (мягкая ссылка, без FK — избегаем лишних cascade-путей).
    depends_on_task_id: Mapped[int | None] = mapped_column(Integer, default=None)
    # task | objective | external
    dependency_type: Mapped[str] = mapped_column(String(20), default="task", nullable=False)
    # pending | satisfied
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
