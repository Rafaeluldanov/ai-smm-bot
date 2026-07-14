"""ContentStrategistService — автономный AI Content Strategist (v0.6.6).

Слой РЕКОМЕНДАЦИЙ поверх AI Learning Profile (v0.6.5), аналитики, SEO и трендов.
Botfleet сам решает «что / когда / для кого / какой формат / какая цель», но НИКОГДА
не применяет это автоматически: только Recommendation → Review → Apply (с подтверждением).

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- стратегия НЕ включает live, НЕ публикует, НЕ вызывает внешние API;
- НЕ меняет активный календарь и НЕ удаляет темы автоматически;
- apply возможен ТОЛЬКО при status=accepted И подтверждении ``APPLY_STRATEGY``;
- apply меняет лишь ``content_rules`` и/или создаёт ЧЕРНОВИК календаря (draft) — не live;
- каждое изменение статуса/профиля пишется в AuditLog; секретов не хранит.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import ai_learning_repository, project_repository
from app.repositories import content_strategy_repository as repo
from app.services import audit_log_service as audit_actions
from app.services.seo_strategy_adapter import SeoStrategyAdapter
from app.services.trend_strategy_adapter import TrendStrategyAdapter

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.content_strategy_profile import ContentStrategyProfile
    from app.models.content_strategy_recommendation import ContentStrategyRecommendation
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

# Подтверждение, обязательное для применения рекомендации.
APPLY_CONFIRMATION = "APPLY_STRATEGY"

# Веса компонентов оценки темы (в сумме 100).
_W_LEARNING = 25.0
_W_ANALYTICS = 25.0
_W_BUSINESS = 20.0
_W_SEO = 20.0
_W_TREND = 10.0

# Бизнес-цель → ключевые слова для совпадения с темой.
_GOAL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "sales": ("прода", "акци", "оффер", "скидк", "купит", "заказ"),
    "leads": ("заявк", "лид", "консультац", "заказ"),
    "brand": ("бренд", "доверие", "истори", "ценност", "команд"),
    "trust": ("кейс", "отзыв", "доверие", "результат", "гарант"),
    "reach": ("охват", "тренд", "подборк", "вирус"),
    "expertise": ("эксперт", "разбор", "гайд", "инструкц", "совет"),
}


class ContentStrategistError(Exception):
    """Ошибка стратега (нет проекта/рекомендации/подтверждения) — API → 400/404."""


class ContentStrategistService:
    """Автономный контент-стратег: снапшот → рекомендации → review → apply."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
        seo_adapter: SeoStrategyAdapter | None = None,
        trend_adapter: TrendStrategyAdapter | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings
        self._seo = seo_adapter or SeoStrategyAdapter()
        self._trend = trend_adapter or TrendStrategyAdapter()

    # ------------------------------------------------------------------ #
    # Профиль / чтение                                                   #
    # ------------------------------------------------------------------ #

    def get_or_create_profile(self, db: Session, project_id: int) -> ContentStrategyProfile:
        """Создать/получить профиль стратегии проекта."""
        self._require_project(db, project_id)
        return repo.get_or_create_profile(
            db, project_id, account_id=self._account_id(db, project_id)
        )

    def get_strategy(self, db: Session, project_id: int) -> dict[str, Any]:
        """Текущая стратегия проекта (профиль + краткий снапшот)."""
        profile = self.get_or_create_profile(db, project_id)
        return {
            **repo.public_profile_view(profile),
            "recommendations_open": len(
                repo.list_recommendations(db, project_id, status="generated")
            ),
        }

    # ------------------------------------------------------------------ #
    # Снапшот стратегии                                                  #
    # ------------------------------------------------------------------ #

    def build_strategy_snapshot(self, db: Session, project_id: int) -> dict[str, Any]:
        """Собрать снапшот стратегии из бизнес-цели, обучения, аналитики, SEO и трендов."""
        self._require_project(db, project_id)
        profile = repo.get_or_create_profile(
            db, project_id, account_id=self._account_id(db, project_id)
        )
        warnings: list[str] = []

        business_goal = self._business_goal(db, project_id, profile)
        learning = ai_learning_repository.get_profile(db, project_id)
        if learning is None or not learning.learning_score:
            warnings.append("Недостаточно данных обучения — соберём после публикаций и метрик.")

        analytics = self._analytics_summary(db, project_id)
        winners = self._winners(db, project_id)
        failures = self._failures(db, project_id)
        seo_signal = self._seo.get_seo_signal(db, project_id)
        if not seo_signal.get("supported"):
            warnings.append("SEO-профиль проекта не настроен — используем общие сигналы спроса.")
        trends = self._trend.get_trending_topics(self._project_slug(db, project_id))

        best_topics = self._best_topics(learning, analytics, winners)
        weak_topics = self._weak_topics(learning, failures)
        best_formats = self._best_formats(learning, analytics)
        pillars = self._content_pillars(best_topics, analytics, trends)
        frequency = self._recommended_frequency(db, project_id)
        audience = self._target_audience(analytics, learning)

        # Персистим агрегаты в профиль (это НЕ применение стратегии, только память).
        repo.update_profile(
            db,
            profile,
            status="active",
            business_goal=business_goal,
            target_audience=audience,
            content_pillars=pillars,
            preferred_topics=best_topics[:10],
            avoided_topics=weak_topics[:10],
            preferred_formats=best_formats[:5],
            posting_strategy={"recommended_frequency": frequency},
            seasonality_rules=seo_signal.get("seasonality", {}),
            last_strategy_update=datetime.now(UTC),
        )
        return {
            "project_id": project_id,
            "business_goal": business_goal,
            "content_pillars": pillars,
            "recommended_frequency": frequency,
            "best_formats": best_formats,
            "best_topics": best_topics[:8],
            "weak_topics": weak_topics[:8],
            "target_audience": audience,
            "seo": {
                "supported": seo_signal.get("supported"),
                "avg_search_demand": seo_signal.get("avg_search_demand"),
                "keywords": seo_signal.get("keywords", [])[:10],
            },
            "trends": trends,
            "warnings": warnings,
        }

    # ------------------------------------------------------------------ #
    # Оценка темы                                                        #
    # ------------------------------------------------------------------ #

    def score_topic(self, db: Session, project_id: int, topic: str) -> dict[str, Any]:
        """Оценка темы 0..100 = learning + analytics + business + seo + trend."""
        self._require_project(db, project_id)
        components = self._score_components(db, project_id, topic)
        return {
            "topic": topic,
            "score": round(sum(components.values()), 1),
            "components": components,
        }

    def _score_components(self, db: Session, project_id: int, topic: str) -> dict[str, float]:
        learning = round(self._learning_topic_score(db, project_id, topic) * _W_LEARNING, 1)
        analytics = round(self._analytics_topic_score(db, project_id, topic) * _W_ANALYTICS, 1)
        business = round(self._business_topic_score(db, project_id, topic) * _W_BUSINESS, 1)
        seo = round(self._seo.score_topic_seo(db, project_id, topic) * _W_SEO, 1)
        slug = self._project_slug(db, project_id)
        trend = round(self._trend.score_topic_trend(topic, slug) * _W_TREND, 1)
        return {
            "learning": learning,
            "analytics": analytics,
            "business": business,
            "seo": seo,
            "trend": trend,
        }

    # ------------------------------------------------------------------ #
    # Генерация рекомендаций                                             #
    # ------------------------------------------------------------------ #

    def generate_recommendations(
        self,
        db: Session,
        project_id: int,
        user_id: int | None = None,
        snapshot: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Сгенерировать стратегические рекомендации (Recommendation → Review → Apply)."""
        self._require_project(db, project_id)
        if not self._resolve_settings().content_strategy_enabled_effective:
            return []
        snapshot = snapshot or self.build_strategy_snapshot(db, project_id)
        account_id = self._account_id(db, project_id)
        # Дедуп по (type, title) среди ВСЕХ статусов: уже применённые/отклонённые
        # рекомендации не пересоздаются (иначе detерминированные title плодят дубли).
        existing = {
            (r.recommendation_type, r.title) for r in repo.list_recommendations(db, project_id)
        }
        created: list[dict[str, Any]] = []

        def _add(rec_type: str, title: str, **kw: Any) -> None:
            if (rec_type, title) in existing:
                return
            row = repo.create_recommendation(
                db,
                project_id=project_id,
                account_id=account_id,
                recommendation_type=rec_type,
                title=title,
                **kw,
            )
            existing.add((rec_type, title))
            created.append(repo.public_recommendation_view(row))

        # 1) Усилить сильные темы.
        for topic in snapshot["best_topics"][:3]:
            score = self.score_topic(db, project_id, str(topic))
            _add(
                "topic",
                f"Больше контента по теме «{topic}»",
                description=f"Тема «{topic}» показывает сильные сигналы — стоит усилить.",
                priority=90,
                confidence_score=score["score"],
                reasoning=self._topic_reasons(score),
                source_signals=[k for k, v in score["components"].items() if v > 0],
                expected_impact={"engagement": "рост", "reach": "рост"},
                apply_payload={"content_rules": {"preferred_topics": [str(topic)]}},
            )
        # 2) Снизить слабые темы.
        for topic in snapshot["weak_topics"][:2]:
            _add(
                "topic",
                f"Меньше контента по теме «{topic}»",
                description=f"Тема «{topic}» слабо заходит — снизить долю.",
                priority=60,
                confidence_score=55.0,
                reasoning=["Низкая эффективность по метрикам/обучению"],
                source_signals=["analytics", "learning"],
                expected_impact={"quality": "рост"},
                apply_payload={},
            )
        # 3) Сильные форматы.
        if snapshot["best_formats"]:
            fmts = ", ".join(str(f) for f in snapshot["best_formats"][:3])
            _add(
                "format",
                f"Делать больше форматов: {fmts}",
                description="Эти форматы дают лучший отклик у аудитории.",
                priority=80,
                confidence_score=70.0,
                reasoning=["Форматы с высоким перф-скором по обучению/аналитике"],
                source_signals=["learning", "analytics"],
                expected_impact={"engagement": "рост"},
                apply_payload={"content_rules": {"preferred_topics": snapshot["best_topics"][:5]}},
            )
        # 4) Расписание.
        _add(
            "schedule",
            f"Частота публикаций: {snapshot['recommended_frequency']}",
            description="Рекомендованная частота на основе активности и обучения.",
            priority=70,
            confidence_score=65.0,
            reasoning=["Оптимальная частота по обучению и аналитике"],
            source_signals=["learning", "analytics"],
            expected_impact={"consistency": "рост"},
            apply_payload={"calendar": {"frequency": snapshot["recommended_frequency"]}},
        )
        # 5) Кампания из тренда.
        if snapshot["trends"]:
            top_trend = snapshot["trends"][0]
            _add(
                "campaign",
                f"Мини-кампания: {top_trend['topic']}",
                description=top_trend.get("reason", ""),
                priority=50,
                confidence_score=round(float(top_trend.get("score", 0.0)) * 100, 1),
                reasoning=[top_trend.get("reason", "Трендовое направление")],
                source_signals=["trend"],
                expected_impact={"reach": "рост"},
                apply_payload={},
            )

        self._write_audit(
            db,
            audit_actions.ACTION_STRATEGY_GENERATED,
            project_id,
            user_id,
            {"created": len(created)},
        )
        return created

    # ------------------------------------------------------------------ #
    # Месячная стратегия                                                 #
    # ------------------------------------------------------------------ #

    def recommend_next_month(
        self, db: Session, project_id: int, snapshot: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Месячная стратегия (4 недели): тема/темы/форматы/цель. Без записи."""
        snapshot = snapshot or self.build_strategy_snapshot(db, project_id)
        pillars = snapshot["content_pillars"] or [{"name": "Экспертность"}]
        topics = snapshot["best_topics"] or ["Экспертный контент"]
        formats = snapshot["best_formats"] or ["expert"]
        goal = snapshot["business_goal"]
        weeks = []
        for i in range(4):
            pillar = pillars[i % len(pillars)]
            theme = pillar.get("name") if isinstance(pillar, dict) else str(pillar)
            week_topics = [topics[(i + j) % len(topics)] for j in range(2)]
            weeks.append(
                {
                    "week": i + 1,
                    "theme": theme,
                    "topics": week_topics,
                    "formats": formats[:2],
                    "goal": goal,
                }
            )
        return {"project_id": project_id, "goal": goal, "weeks": weeks}

    # ------------------------------------------------------------------ #
    # Объяснение                                                         #
    # ------------------------------------------------------------------ #

    def explain_strategy(self, db: Session, project_id: int) -> dict[str, Any]:
        """Объяснение для клиента: почему бот выбрал эти темы/форматы."""
        profile = self.get_or_create_profile(db, project_id)
        reasons: list[str] = []
        if profile.preferred_topics:
            reasons.append(
                "Сильные темы: " + ", ".join(str(t) for t in profile.preferred_topics[:3])
            )
        if profile.avoided_topics:
            reasons.append(
                "Слабые темы (реже): " + ", ".join(str(t) for t in profile.avoided_topics[:3])
            )
        if profile.preferred_formats:
            reasons.append(
                "Рабочие форматы: " + ", ".join(str(f) for f in profile.preferred_formats[:3])
            )
        if profile.business_goal:
            reasons.append(f"Бизнес-цель: {profile.business_goal}")
        freq = (profile.posting_strategy or {}).get("recommended_frequency")
        if freq:
            reasons.append(f"Рекомендованная частота: {freq}")
        if not reasons:
            reasons.append("Пока мало данных — запустите анализ после нескольких публикаций.")
        return {
            "project_id": project_id,
            "status": profile.status,
            "business_goal": profile.business_goal,
            "content_pillars": list(profile.content_pillars or []),
            "reasons": reasons,
        }

    # ------------------------------------------------------------------ #
    # Review flow                                                        #
    # ------------------------------------------------------------------ #

    def accept_recommendation(
        self, db: Session, project_id: int, recommendation_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Одобрить рекомендацию (status=accepted)."""
        rec = self._require_recommendation(db, project_id, recommendation_id)
        if rec.status in ("applied",):
            raise ContentStrategistError("Рекомендация уже применена")
        repo.approve(db, rec)
        self._write_audit(
            db, audit_actions.ACTION_STRATEGY_ACCEPTED, project_id, user_id, {"rec_id": rec.id}
        )
        return repo.public_recommendation_view(rec)

    def reject_recommendation(
        self, db: Session, project_id: int, recommendation_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Отклонить рекомендацию (status=rejected)."""
        rec = self._require_recommendation(db, project_id, recommendation_id)
        if rec.status in ("applied",):
            raise ContentStrategistError("Рекомендация уже применена")
        repo.reject(db, rec)
        self._write_audit(
            db, audit_actions.ACTION_STRATEGY_REJECTED, project_id, user_id, {"rec_id": rec.id}
        )
        return repo.public_recommendation_view(rec)

    def apply_recommendation(
        self,
        db: Session,
        project_id: int,
        recommendation_id: int,
        confirmation: str = "",
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Применить рекомендацию. ТОЛЬКО при status=accepted И confirmation=APPLY_STRATEGY.

        Может изменить ``content_rules`` и/или создать ЧЕРНОВИК календаря (draft). НЕ
        включает live, НЕ публикует, НЕ меняет активный календарь.
        """
        rec = self._require_recommendation(db, project_id, recommendation_id)
        if rec.status != "accepted":
            raise ContentStrategistError("Сначала одобрите рекомендацию (accept)")
        if confirmation != APPLY_CONFIRMATION:
            raise ContentStrategistError("Требуется подтверждение APPLY_STRATEGY")

        payload = dict(rec.apply_payload or {})
        applied: dict[str, Any] = {"content_rules": False, "calendar_draft": False}
        if payload.get("content_rules"):
            self._apply_content_rules(db, project_id, payload["content_rules"], user_id)
            applied["content_rules"] = True
        if payload.get("calendar"):
            self._apply_calendar_draft(db, project_id, payload["calendar"], user_id)
            applied["calendar_draft"] = True

        repo.apply(db, rec)
        self._write_audit(
            db,
            audit_actions.ACTION_STRATEGY_APPLIED,
            project_id,
            user_id,
            {"rec_id": rec.id, "applied": applied},
        )
        return {
            "recommendation": repo.public_recommendation_view(rec),
            "applied": applied,
            "live_enabled": False,  # инвариант: apply НЕ включает live и НЕ публикует
            "note": "Изменены только правила/черновик календаря. Публикация не запускалась.",
        }

    # ------------------------------------------------------------------ #
    # Календарь-превью (без записи)                                      #
    # ------------------------------------------------------------------ #

    def calendar_strategy_preview(self, db: Session, project_id: int) -> dict[str, Any]:
        """Предпросмотр календаря «если применить стратегию». Без записи."""
        self._require_project(db, project_id)
        try:
            from app.services.autopilot_calendar_assistant_service import (
                AutopilotCalendarAssistantService,
            )

            assistant = AutopilotCalendarAssistantService(settings=self._resolve_settings())
            recommended = assistant.recommend_calendar(db, project_id)
            preset = recommended.get("recommended_preset")
            preview = assistant.create_calendar_plan(
                db,
                project_id,
                {"preset": preset, "goal": recommended.get("goal")},
                current_user_id=None,
                dry_run=True,  # гарантированно без записи
            )
            return {"recommended": recommended, "preview": preview, "writes": False}
        except Exception as exc:  # noqa: BLE001 — превью не критично
            logger.warning("calendar strategy preview failed: %s", type(exc).__name__)
            return {"recommended": {}, "preview": {}, "writes": False}

    # ------------------------------------------------------------------ #
    # Recommendations listing                                            #
    # ------------------------------------------------------------------ #

    def list_recommendations(
        self, db: Session, project_id: int, status: str | None = None
    ) -> list[dict[str, Any]]:
        """Список рекомендаций проекта (по статусу)."""
        self._require_project(db, project_id)
        return [
            repo.public_recommendation_view(r)
            for r in repo.list_recommendations(db, project_id, status=status)
        ]

    # ------------------------------------------------------------------ #
    # Внутреннее: apply-эффекты (только безопасные)                      #
    # ------------------------------------------------------------------ #

    def _apply_content_rules(
        self, db: Session, project_id: int, rules: dict[str, Any], user_id: int | None
    ) -> None:
        from app.repositories import autopilot_repository
        from app.services.autopilot_service import AutopilotService

        # Слияние с текущими правилами: apply НЕ должен затирать уже настроенные
        # business_goal/tone/cta и, главное, guardrail `forbidden_phrases`.
        merged: dict[str, Any] = {}
        ap = autopilot_repository.get_profile_by_project_id(db, project_id)
        if ap is not None and isinstance(ap.content_rules, dict):
            merged.update(ap.content_rules)
        merged.update(rules)
        AutopilotService(settings=self._resolve_settings()).configure_content_rules(
            db, project_id, merged, user_id
        )

    def _apply_calendar_draft(
        self, db: Session, project_id: int, calendar: dict[str, Any], user_id: int | None
    ) -> None:
        from app.services.autopilot_calendar_assistant_service import (
            AutopilotCalendarAssistantService,
        )

        assistant = AutopilotCalendarAssistantService(settings=self._resolve_settings())
        recommended = assistant.recommend_calendar(db, project_id)
        preset = calendar.get("preset") or recommended.get("recommended_preset")
        # dry_run=False создаёт ЧЕРНОВИК (status=draft) — не публикует и не активирует.
        assistant.create_calendar_plan(
            db,
            project_id,
            {"preset": preset, "goal": recommended.get("goal")},
            current_user_id=user_id,
            dry_run=False,
        )

    # ------------------------------------------------------------------ #
    # Внутреннее: сбор сигналов                                          #
    # ------------------------------------------------------------------ #

    def _business_goal(self, db: Session, project_id: int, profile: ContentStrategyProfile) -> str:
        if profile.business_goal:
            return profile.business_goal
        try:
            from app.repositories import autopilot_repository

            ap = autopilot_repository.get_profile_by_project_id(db, project_id)
            if ap is not None and ap.content_rules:
                goal = (ap.content_rules or {}).get("business_goal")
                if goal:
                    return str(goal)
        except Exception:  # noqa: BLE001 — вспомогательный источник не критичен
            pass
        return "mixed"

    def _analytics_summary(self, db: Session, project_id: int) -> Any | None:
        try:
            from app.services.analytics_service import AnalyticsService

            return AnalyticsService().get_project_summary(db, project_id)
        except Exception:  # noqa: BLE001 — аналитика может быть пустой
            return None

    def _winners(self, db: Session, project_id: int) -> list[dict[str, Any]]:
        try:
            from app.services.post_performance_learning_service import (
                PostPerformanceLearningService,
            )

            return PostPerformanceLearningService().detect_winners(db, project_id, limit=5)
        except Exception:  # noqa: BLE001
            return []

    def _failures(self, db: Session, project_id: int) -> list[dict[str, Any]]:
        try:
            from app.services.post_performance_learning_service import (
                PostPerformanceLearningService,
            )

            return PostPerformanceLearningService().detect_failures(db, project_id, limit=5)
        except Exception:  # noqa: BLE001
            return []

    def _recommended_frequency(self, db: Session, project_id: int) -> str:
        try:
            from app.services.content_strategy_service import ContentStrategyService

            strat = ContentStrategyService().recommend_strategy(db, project_id)
            return str(strat.get("posting_frequency") or "3_week")
        except Exception:  # noqa: BLE001
            return "3_week"

    @staticmethod
    def _best_topics(learning: Any, analytics: Any, winners: list[dict[str, Any]]) -> list[str]:
        out: list[str] = []
        if learning is not None:
            out.extend(str(t) for t in (learning.preferred_topics or []))
        if analytics is not None:
            for item in getattr(analytics, "top_topics", []) or []:
                title = getattr(item, "topic_title", None)
                if title:
                    out.append(str(title))
        return _dedup(out)

    @staticmethod
    def _weak_topics(learning: Any, failures: list[dict[str, Any]]) -> list[str]:
        out: list[str] = []
        if learning is not None:
            out.extend(str(t) for t in (learning.avoided_topics or []))
        return _dedup(out)

    @staticmethod
    def _best_formats(learning: Any, analytics: Any) -> list[str]:
        out: list[str] = []
        if learning is not None:
            out.extend(str(f) for f in (learning.preferred_formats or []))
        return _dedup(out)

    @staticmethod
    def _content_pillars(
        best_topics: list[str], analytics: Any, trends: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        pillars: list[dict[str, Any]] = []
        seen: set[str] = set()
        for topic in best_topics[:3]:
            key = str(topic).lower()
            if key not in seen:
                seen.add(key)
                pillars.append({"name": str(topic), "source": "learning/analytics"})
        if analytics is not None:
            for item in getattr(analytics, "top_clusters", []) or []:
                name = getattr(item, "cluster", None)
                if name and str(name).lower() not in seen:
                    seen.add(str(name).lower())
                    pillars.append({"name": str(name), "source": "analytics"})
        if len(pillars) < 3 and trends:
            for trend in trends:
                name = trend.get("topic")
                if name and str(name).lower() not in seen:
                    seen.add(str(name).lower())
                    pillars.append({"name": str(name), "source": "trend"})
                if len(pillars) >= 3:
                    break
        return pillars[:5]

    @staticmethod
    def _target_audience(analytics: Any, learning: Any) -> dict[str, Any]:
        audience: dict[str, Any] = {}
        if analytics is not None:
            audience["best_platform"] = (getattr(learning, "best_platforms", None) or [])[:1]
        if learning is not None and learning.best_platforms:
            audience["platforms"] = list(learning.best_platforms or [])[:3]
        return audience

    # --- компоненты оценки темы ---

    @staticmethod
    def _learning_topic_score(db: Session, project_id: int, topic: str) -> float:
        profile = ai_learning_repository.get_profile(db, project_id)
        if profile is None:
            return 0.4
        topic_l = topic.strip().lower()
        preferred = {str(t).lower() for t in (profile.preferred_topics or [])}
        avoided = {str(t).lower() for t in (profile.avoided_topics or [])}
        if any(topic_l in p or p in topic_l for p in preferred):
            return 1.0
        if any(topic_l in a or a in topic_l for a in avoided):
            return 0.0
        return 0.4

    def _analytics_topic_score(self, db: Session, project_id: int, topic: str) -> float:
        try:
            from app.services.analytics_service import AnalyticsService

            report = AnalyticsService().get_topic_performance(db, project_id)
        except Exception:  # noqa: BLE001
            return 0.3
        topic_l = topic.strip().lower()
        for item in getattr(report, "items", []) or []:
            title = str(getattr(item, "topic_title", "") or "").lower()
            if title and (topic_l in title or title in topic_l):
                return max(0.0, min(1.0, float(getattr(item, "performance_score", 0.0)) / 100.0))
        return 0.3

    def _business_topic_score(self, db: Session, project_id: int, topic: str) -> float:
        # Только чтение — score_topic не должен создавать/писать профиль как побочный эффект.
        profile = repo.get_profile(db, project_id)
        goal = (profile.business_goal if profile is not None else None) or "mixed"
        keywords = _GOAL_KEYWORDS.get(str(goal), ())
        topic_l = topic.strip().lower()
        if keywords and any(kw in topic_l for kw in keywords):
            return 0.9
        return 0.4

    @staticmethod
    def _topic_reasons(score: dict[str, Any]) -> list[str]:
        comps = score.get("components", {})
        reasons: list[str] = []
        if comps.get("learning", 0) >= 20:
            reasons.append("AI Learning profile: тема из сильных")
        if comps.get("analytics", 0) >= 15:
            reasons.append("Аналитика: высокий перф-скор")
        if comps.get("seo", 0) >= 10:
            reasons.append("SEO: заметный поисковый спрос")
        if comps.get("trend", 0) >= 5:
            reasons.append("Тренд: направление в тренде")
        if comps.get("business", 0) >= 15:
            reasons.append("Совпадает с бизнес-целью")
        if not reasons:
            reasons.append("Сбалансированный сигнал по нескольким источникам")
        return reasons

    # ------------------------------------------------------------------ #
    # Инфраструктура                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _project_slug(db: Session, project_id: int) -> str:
        project = project_repository.get_project_by_id(db, project_id)
        return str(getattr(project, "slug", "") or "") if project is not None else ""

    def _require_project(self, db: Session, project_id: int) -> Any:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise ContentStrategistError(f"Проект id={project_id} не найден")
        return project

    def _require_recommendation(
        self, db: Session, project_id: int, recommendation_id: int
    ) -> ContentStrategyRecommendation:
        rec = repo.get_recommendation_by_id(db, recommendation_id)
        if rec is None or rec.project_id != project_id:
            raise ContentStrategistError("Рекомендация не найдена")
        return rec

    @staticmethod
    def _account_id(db: Session, project_id: int) -> int | None:
        project = project_repository.get_project_by_id(db, project_id)
        return project.account_id if project is not None else None

    def _resolve_settings(self) -> Settings:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _write_audit(
        self,
        db: Session,
        action: str,
        project_id: int,
        user_id: int | None,
        metadata: dict[str, Any],
    ) -> None:
        if self._audit_svc is None:
            from app.services.audit_log_service import AuditLogService

            self._audit_svc = AuditLogService(self._resolve_settings())
        self._audit_svc.record(
            db,
            action,
            account_id=self._account_id(db, project_id),
            user_id=user_id,
            project_id=project_id,
            entity_type="content_strategy_profile",
            metadata=metadata,
        )


def _dedup(items: list[str]) -> list[str]:
    """Дедуп с сохранением порядка (регистронезависимо)."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = str(item).strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(str(item))
    return out


def get_content_strategist_service() -> ContentStrategistService:
    """DI-фабрика автономного контент-стратега."""
    return ContentStrategistService()
