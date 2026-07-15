"""Сигнал решения (v0.7.4) — вход для оценки в AI Decision Engine.

Сигнал — взвешенный факт о состоянии бизнеса из смежного слоя (Operations Center, Growth
Agent, Sales Intelligence, Campaign Manager, Workflow Manager), который учитывается при
построении и оценке сценариев. Append-only (без обновления).

БЕЗОПАСНОСТЬ:
- сигнал — только чтение/аналитика; секретов не содержит.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType


class DecisionSignal(Base):
    """Один взвешенный сигнал AI-решения (per-decision, append-only, без секретов)."""

    __tablename__ = "decision_signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    decision_id: Mapped[int] = mapped_column(
        ForeignKey("ai_decisions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # operations_center | growth_agent | sales_intelligence | campaign_manager | workflow_manager
    source_module: Mapped[str] = mapped_column(String(40), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(40), nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
