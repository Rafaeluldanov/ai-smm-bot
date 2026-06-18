"""Мост аналитики и выбора тем (Этап 8).

Превращает аналитику кластеров в корректировки бизнес-приоритетов и текстовые
заметки. Используется как лёгкая, не ломающая Этап 4, интеграция: на будущем
этапе результат можно подмешивать в ``TopicSelectionService``.
"""

from sqlalchemy.orm import Session

from app.services.analytics_service import AnalyticsService

# Пороги performance_score для корректировки приоритета кластера.
_BOOST_SCORE = 60.0
_PENALTY_SCORE = 25.0
_BOOST_VALUE = 10
_PENALTY_VALUE = -10


class TopicAnalyticsFeedbackService:
    """Строит корректировки приоритетов и заметки из аналитики кластеров."""

    def __init__(self, analytics_service: AnalyticsService) -> None:
        self._analytics = analytics_service

    def build_business_priority_adjustments(self, db: Session, project_id: int) -> dict[str, int]:
        """Вернуть {cluster: adjustment} по эффективности кластеров."""
        report = self._analytics.get_cluster_performance(db, project_id)
        adjustments: dict[str, int] = {}
        for item in report.items:
            if item.performance_score > _BOOST_SCORE:
                adjustments[item.cluster] = _BOOST_VALUE
            elif item.performance_score < _PENALTY_SCORE:
                adjustments[item.cluster] = _PENALTY_VALUE
        return adjustments

    def build_feedback_notes(self, db: Session, project_id: int) -> list[str]:
        """Вернуть человекочитаемые заметки из feedback-сигналов и предупреждений."""
        feedback = self._analytics.build_feedback_signals(db, project_id)
        notes = [
            f"[{signal.signal_type}] {signal.cluster}: {signal.reason} (value={signal.value})"
            for signal in feedback.signals
        ]
        notes.extend(feedback.warnings)
        return notes
