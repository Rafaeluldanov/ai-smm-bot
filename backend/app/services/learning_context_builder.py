"""LearningContextBuilder — контекст обучения для генерации (v0.6.5).

Собирает безопасный «контекст обучения» проекта (предпочтительные темы/тон/форматы/
запрещённые темы/CTA/лучшее время) из :class:`AILearningProfile` (+ существующего
:class:`ClientLearningProfile`) и отдаёт его генерации.

ВАЖНО: генератор напрямую НЕ меняется. Контекст — опциональный вход:
``PostGenerationService`` принимает его как необязательный параметр и, если он передан,
лишь мягко смещает выбор формата/CTA (при None — поведение прежнее). Секретов нет.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.repositories import ai_learning_repository, client_learning_repository

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session


class LearningContextBuilder:
    """Строит контекст обучения проекта для подсказок генерации (без публикаций)."""

    def build_context(self, db: Session, project_id: int) -> dict[str, Any]:
        """Безопасный контекст обучения проекта (пустой, если профиля ещё нет)."""
        profile = ai_learning_repository.get_profile(db, project_id)
        cl_profile = None
        try:
            cl_profile = client_learning_repository.get_profile(db, project_id)
        except Exception:  # noqa: BLE001 — вспомогательный источник не критичен
            cl_profile = None

        preferred_topics: list[str] = []
        forbidden_themes: list[str] = []
        preferred_formats: list[str] = []
        preferred_cta: list[str] = []
        preferred_tone = ""
        best_time = ""
        has_learning = False

        if profile is not None:
            preferred_topics = [str(t) for t in (profile.preferred_topics or [])]
            forbidden_themes = [str(t) for t in (profile.avoided_topics or [])]
            preferred_formats = [str(f) for f in (profile.preferred_formats or [])]
            styles = list(profile.preferred_styles or [])
            preferred_tone = str(styles[0]) if styles else ""
            times = list(profile.best_publish_times or [])
            best_time = str(times[0]) if times else ""
            cta_pref = (profile.cta_preferences or {}).get("preferred")
            if cta_pref:
                preferred_cta = [str(c) for c in cta_pref]
            has_learning = bool(profile.learning_score and profile.learning_score > 0)

        # Дополняем существующим профилем обучения (reuse, не дублируем).
        if cl_profile is not None:
            if not preferred_cta:
                preferred_cta = [str(c) for c in (getattr(cl_profile, "preferred_cta", []) or [])]
            if not preferred_topics:
                preferred_topics = [
                    str(t) for t in (getattr(cl_profile, "preferred_topics", []) or [])
                ]

        return {
            "project_id": project_id,
            "has_learning": has_learning,
            "preferred_topics": preferred_topics[:8],
            "forbidden_themes": forbidden_themes[:8],
            "preferred_formats": preferred_formats[:5],
            "preferred_tone": preferred_tone,
            "preferred_cta": preferred_cta[:5],
            "best_time": best_time,
        }

    @staticmethod
    def preferred_format(context: dict[str, Any] | None) -> str | None:
        """Извлечь предпочтительный формат из контекста (или None)."""
        if not context:
            return None
        formats = context.get("preferred_formats") or []
        return str(formats[0]) if formats else None

    @staticmethod
    def preferred_cta(context: dict[str, Any] | None) -> str | None:
        """Извлечь предпочтительный CTA из контекста (или None)."""
        if not context:
            return None
        ctas = context.get("preferred_cta") or []
        return str(ctas[0]) if ctas else None


def get_learning_context_builder() -> LearningContextBuilder:
    """DI-фабрика построителя контекста обучения."""
    return LearningContextBuilder()
