"""ContentStrategyService — рекомендация контент-стратегии (v0.6.5).

Собирает из :class:`AILearningProfile` цельную рекомендацию стратегии (частота/темы/
форматы/тон/CTA/стиль медиа). Это ТОЛЬКО рекомендация: сервис ничего не применяет
автоматически, не меняет расписание/стратегию, не публикует и не трогает live-флаги.
Изменения в реальную стратегию клиент вносит сам (через календарь/автопилот) — с audit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.repositories import ai_learning_repository

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session


class ContentStrategyService:
    """Строит рекомендацию контент-стратегии по профилю обучения (без применения)."""

    def recommend_strategy(self, db: Session, project_id: int) -> dict[str, Any]:
        """Рекомендованная стратегия (частота/темы/форматы/тон/CTA/медиа). Не применяется."""
        profile = ai_learning_repository.get_profile(db, project_id)
        if profile is None:
            return {
                "project_id": project_id,
                "has_learning": False,
                "posting_frequency": "3_week",
                "topics": [],
                "formats": [],
                "tone": "",
                "cta": [],
                "media_style": "",
                "confidence": 0.0,
                "note": "Недостаточно данных — рекомендация по умолчанию (не применяется).",
            }

        score = float(profile.learning_score or 0.0)
        media_style = (profile.media_preferences or {}).get("best_media_type", "")
        cta = (profile.cta_preferences or {}).get("preferred", [])
        styles = list(profile.preferred_styles or [])
        return {
            "project_id": project_id,
            "has_learning": bool(score > 0),
            "posting_frequency": self._recommend_frequency(profile),
            "topics": list(profile.preferred_topics or [])[:5],
            "formats": list(profile.preferred_formats or [])[:3],
            "tone": str(styles[0]) if styles else "",
            "cta": [str(c) for c in cta][:3],
            "media_style": str(media_style),
            "avoid_topics": list(profile.avoided_topics or [])[:5],
            "avoid_formats": list(profile.avoided_formats or [])[:3],
            "best_times": list(profile.best_publish_times or [])[:3],
            "confidence": round(score, 1),
            "note": "Рекомендация. Стратегию вы меняете сами — автопилот её не применяет сам.",
        }

    @staticmethod
    def _recommend_frequency(profile: Any) -> str:
        """Частота публикаций по «полезности» контента и числу сильных слотов времени.

        Консервативно: без явного сигнала — умеренная частота ``3_week``.
        """
        rules = profile.content_rules or {}
        useful = int(rules.get("useful_content_signals", 0) or 0)
        strong_times = len(profile.best_publish_times or [])
        score = float(profile.learning_score or 0.0)
        if score >= 70 and useful >= 3 and strong_times >= 2:
            return "daily"
        if score >= 40 and (useful >= 1 or strong_times >= 1):
            return "3_week"
        return "weekly"


def get_content_strategy_service() -> ContentStrategyService:
    """DI-фабрика сервиса рекомендации стратегии."""
    return ContentStrategyService()
