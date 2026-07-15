"""Рекомендация эффективности (v0.7.9) — совет по улучшению результата.

Рекомендация по устранению отклонения: приоритет, ожидаемый эффект, статус. Только совет.

БЕЗОПАСНОСТЬ:
- рекомендация — только совет; НЕ выполняется автоматически; секретов не содержит.
"""

from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class PerformanceRecommendation(Base, TimestampMixin):
    """Рекомендация по эффективности (per-snapshot, без секретов)."""

    __tablename__ = "performance_recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("performance_snapshots.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # critical | high | medium | low
    priority: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    expected_effect: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    # generated | accepted | rejected
    status: Mapped[str] = mapped_column(String(20), default="generated", nullable=False)
