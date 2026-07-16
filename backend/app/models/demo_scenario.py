"""Demo-сценарий (v0.9.0) — прогон E2E-теста AI Business OS через demo-воркспейс.

Хранит тип сценария, статус, вход (input_data), результат по этапам (result_data) и общий score.
Это результат тестового прогона: реального бизнеса/CRM/workflow не затрагивает.

БЕЗОПАСНОСТЬ:
- сценарий — только запись прогона E2E-теста; секретов не содержит; внешних действий не выполняет.
"""

from typing import Any

from sqlalchemy import Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# Тип demo-сценария.
SCENARIO_TYPES: tuple[str, ...] = ("growth", "recovery", "optimization")
# Статус прогона сценария.
SCENARIO_STATUSES: tuple[str, ...] = ("draft", "running", "completed", "failed")


class DemoScenario(Base, TimestampMixin):
    """Прогон demo-сценария (per-workspace, без секретов)."""

    __tablename__ = "demo_scenarios"
    __table_args__ = (Index("ix_demo_scenarios_workspace_status", "workspace_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("demo_workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # growth | recovery | optimization
    scenario_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # draft | running | completed | failed
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    input_data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    result_data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
