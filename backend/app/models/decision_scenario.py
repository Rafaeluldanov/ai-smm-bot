"""Сценарий решения (v0.7.4) — вариант в AI Decision Engine.

Сценарий — один из вариантов решения проблемы (усилить CTA / запустить кампанию / сменить
контент-стратегию) с допущениями, ожидаемым эффектом, анализом рисков, оценкой стоимости и
уверенностью. Сценарии оцениваются и сравниваются, лучший рекомендуется.

БЕЗОПАСНОСТЬ:
- сценарий — только анализ/рекомендация; select/reject лишь меняют статус. Секретов нет.
"""

from typing import Any

from sqlalchemy import Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class DecisionScenario(Base, TimestampMixin):
    """Один сценарий (вариант решения) AI-решения (per-decision, без секретов)."""

    __tablename__ = "decision_scenarios"
    __table_args__ = (Index("ix_decision_scenarios_decision_status", "decision_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    decision_id: Mapped[int] = mapped_column(
        ForeignKey("ai_decisions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    assumptions: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    expected_impact: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    risk_analysis: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    cost_estimate: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # generated | evaluated | selected | rejected
    status: Mapped[str] = mapped_column(String(20), default="generated", nullable=False)
