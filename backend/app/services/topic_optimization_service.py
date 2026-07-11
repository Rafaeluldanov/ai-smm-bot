"""Оптимизация тем и рекомендательный слой «что публиковать дальше» (v0.4.2).

Собирает сигналы проекта (feedback, аналитика, метрики, learning profile, недавние
посты) и рекомендует темы: publish_more / avoid / retest / explore / seasonal / fill_gap.
Учитывает свежесть (recency) и «усталость» (fatigue) тем.

БЕЗОПАСНОСТЬ: строго per-project; никаких внешних API; no cross-project mixing.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.repositories import (
    crm_bot_smm_repository,
    post_repository,
)
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:
    from app.config import Settings
    from app.services.audit_log_service import AuditLogService
    from app.services.client_learning_service import ClientLearningService

# Категории рекомендаций.
REC_PUBLISH_MORE = "publish_more"
REC_AVOID = "avoid"
REC_RETEST = "retest"
REC_EXPLORE = "explore"
REC_SEASONAL = "seasonal"
REC_FILL_GAP = "fill_gap"

# Порог «усталости»: сколько раз тема/тег встретились среди недавних постов.
_FATIGUE_COUNT = 3


class TopicOptimizationService:
    """Сводка сигналов проекта + рекомендации тем + скоринг кандидата."""

    def __init__(
        self,
        learning_service: ClientLearningService | None = None,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._learning = learning_service
        self._audit = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # 1. Сводка сигналов проекта                                          #
    # ------------------------------------------------------------------ #

    def build_project_signal_summary(
        self, db: Session, project_id: int, platform_key: str | None = None
    ) -> dict[str, Any]:
        """Собрать сигналы: темы/теги/CTA/медиа/время/паттерны + content gaps."""
        summary = self._learning_svc().summarize_learning(db, project_id, platform_key)
        usage = self._recent_usage(db, project_id)
        gaps = self._content_gaps(db, project_id, summary, usage)
        return {
            "project_id": project_id,
            "platform_key": platform_key,
            "has_profile": summary.get("has_profile", False),
            "confidence_score": summary.get("confidence_score", 0.0),
            "top_topics": summary.get("preferred_topics", []),
            "weak_topics": summary.get("rejected_topics", []),
            "high_performing_tags": summary.get("high_performing_tags", []),
            "low_performing_tags": summary.get("low_performing_tags", []),
            "best_cta_patterns": summary.get("preferred_cta", []),
            "weak_cta_patterns": summary.get("rejected_cta", []),
            "best_media_types": summary.get("preferred_media_types", []),
            "best_publish_times": summary.get("best_publish_times", []),
            "approval_patterns": summary.get("approval_patterns", {}),
            "editing_patterns": summary.get("editing_patterns", {}),
            "performance_patterns": summary.get("performance_patterns", {}),
            "content_gaps": gaps,
            "recommendations": summary.get("recommendations", []),
        }

    # ------------------------------------------------------------------ #
    # 2. Рекомендации следующих тем                                       #
    # ------------------------------------------------------------------ #

    def recommend_next_topics(
        self, db: Session, project_id: int, platform_key: str | None = None, limit: int = 10
    ) -> dict[str, Any]:
        """Рекомендации тем по категориям с причинами/уверенностью/подсказками."""
        limit = min(int(limit or 10), self._max_recommendations())
        summary = self.build_project_signal_summary(db, project_id, platform_key)
        usage = self._recent_usage(db, project_id)
        confidence = float(summary.get("confidence_score", 0.0) or 0.0)
        suggested_cta = _first(summary["best_cta_patterns"])
        suggested_media = _first(summary["best_media_types"])
        suggested_time = _first(summary["best_publish_times"])

        recs: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add(
            topic: str,
            category: str,
            reason: str,
            base_conf: float,
            signals: list[str],
            risk: list[str] | None = None,
        ) -> None:
            key = str(topic).strip().lower()
            if not key or key in seen:
                return
            seen.add(key)
            recs.append(
                {
                    "topic": topic,
                    "category": category,
                    "reason": reason,
                    "confidence_score": round(max(0.0, min(1.0, base_conf)), 3),
                    "source_signals": signals,
                    "suggested_cta": suggested_cta,
                    "suggested_media_type": suggested_media,
                    "suggested_time": suggested_time,
                    "estimated_units": self._experiment_units(),
                    "risk_flags": risk or ([] if confidence >= 0.3 else ["low_data"]),
                }
            )

        # publish_more: одобряемые темы, не «уставшие».
        for topic in summary["top_topics"]:
            fatigue = usage.get(str(topic).lower(), 0) >= _FATIGUE_COUNT
            add(
                topic,
                REC_PUBLISH_MORE,
                "Клиент одобрял такие темы — публикуем чаще.",
                0.5 + confidence * 0.4,
                ["client_feedback"],
                risk=["fatigue"] if fatigue else None,
            )
        # explore: сильные, но недоиспользуемые теги (использованы не больше 1 раза).
        for tag in summary["high_performing_tags"]:
            if usage.get(str(tag).lower().lstrip("#"), 0) <= 1:
                add(
                    f"#{str(tag).lstrip('#')}",
                    REC_EXPLORE,
                    "Сильный тег почти не используется — стоит раскрыть тему.",
                    0.4 + confidence * 0.3,
                    ["api_metrics", "manual_metrics"],
                )
        # fill_gap: категории CRM без недавних постов.
        for gap in summary["content_gaps"]:
            add(
                gap,
                REC_FILL_GAP,
                "Направление есть в плане, но давно не публиковалось.",
                0.35 + confidence * 0.2,
                ["internal_history"],
            )
        # retest: слабые теги/темы, которые стоит проверить иначе.
        for tag in summary["low_performing_tags"]:
            add(
                f"#{str(tag).lstrip('#')}",
                REC_RETEST,
                "Тег работал слабо — переупакуем и протестируем заново (A/B).",
                0.3,
                ["internal_history"],
                risk=["weak_history"],
            )
        # avoid: отклонённые темы.
        for topic in summary["weak_topics"]:
            add(
                topic,
                REC_AVOID,
                "Клиент отклонял такие темы — избегаем.",
                0.6,
                ["client_feedback"],
                risk=["rejected"],
            )

        self._write_audit(
            db,
            project_id,
            audit_actions.ACTION_OPTIMIZATION_RECOMMENDATIONS_GENERATED,
            {"count": len(recs[:limit]), "platform_key": platform_key},
        )
        return {
            "project_id": project_id,
            "platform_key": platform_key,
            "confidence_score": round(confidence, 3),
            "recommendations": recs[:limit],
            "suggested_cta": suggested_cta,
            "suggested_media_type": suggested_media,
            "suggested_time": suggested_time,
        }

    # ------------------------------------------------------------------ #
    # 3. Скоринг кандидата темы                                           #
    # ------------------------------------------------------------------ #

    def score_topic_candidate(
        self, db: Session, project_id: int, platform_key: str | None, topic_payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Оценить тему-кандидат: fit/client/performance/novelty/risk + total."""
        topic = str(topic_payload.get("topic", "")).strip()
        tags = [str(t).lower().lstrip("#") for t in (topic_payload.get("tags") or [])]
        summary = self.build_project_signal_summary(db, project_id, platform_key)
        usage = self._recent_usage(db, project_id)

        high = {str(t).lower().lstrip("#") for t in summary["high_performing_tags"]}
        low = {str(t).lower().lstrip("#") for t in summary["low_performing_tags"]}
        approved = {str(t).lower() for t in summary["top_topics"]}
        rejected = {str(t).lower() for t in summary["weak_topics"]}
        tl = topic.lower()

        reasons: list[str] = []
        topic_fit = 50.0
        if any(t in high for t in tags):
            topic_fit += 25
            reasons.append("Содержит сильные теги")
        if any(t in low for t in tags):
            topic_fit -= 20
            reasons.append("Содержит слабые теги")

        client_fit = 50.0
        if any(a in tl or tl in a for a in approved):
            client_fit += 30
            reasons.append("Похоже на одобряемые темы клиента")
        if any(r in tl or tl in r for r in rejected):
            client_fit -= 40
            reasons.append("Похоже на отклонённые темы")

        perf = summary.get("performance_patterns", {}) or {}
        performance = 50.0 + min(30.0, float(perf.get("avg_engagement_rate", 0.0) or 0.0) * 200)

        used = usage.get(tl, 0)
        novelty = 70.0 if used == 0 else max(10.0, 70.0 - used * 20.0)
        risk = 20.0
        if any(r in tl or tl in r for r in rejected):
            risk += 40
        if used >= _FATIGUE_COUNT:
            risk += 20
            reasons.append("Тема часто повторялась — риск усталости")

        total = (
            0.25 * _clamp(topic_fit)
            + 0.30 * _clamp(client_fit)
            + 0.25 * _clamp(performance)
            + 0.15 * _clamp(novelty)
            - 0.15 * _clamp(risk)
        )
        return {
            "topic": topic,
            "topic_fit_score": int(_clamp(topic_fit)),
            "client_fit_score": int(_clamp(client_fit)),
            "performance_score": int(_clamp(performance)),
            "novelty_score": int(_clamp(novelty)),
            "risk_score": int(_clamp(risk)),
            "total_score": int(_clamp(total)),
            "reasons": reasons,
        }

    # ------------------------------------------------------------------ #
    # 4. Выбор темы для следующего расписания (безопасно, без публикации)  #
    # ------------------------------------------------------------------ #

    def choose_topic_for_next_schedule(
        self,
        db: Session,
        project_id: int,
        platform_key: str | None = None,
        category_id: int | None = None,
    ) -> dict[str, Any]:
        """Вернуть лучшую рекомендацию темы (ничего не публикует)."""
        recs = self.recommend_next_topics(db, project_id, platform_key)["recommendations"]
        preferred = [r for r in recs if r["category"] in (REC_PUBLISH_MORE, REC_EXPLORE)]
        chosen = preferred[0] if preferred else (recs[0] if recs else None)
        if chosen is not None:
            self._write_audit(
                db,
                project_id,
                audit_actions.ACTION_OPTIMIZATION_TOPIC_SELECTED,
                {"topic": chosen["topic"], "category": chosen["category"], "live": False},
            )
        return {
            "project_id": project_id,
            "platform_key": platform_key,
            "category_id": category_id,
            "recommendation": chosen,
            "live": False,
        }

    # ------------------------------------------------------------------ #
    # 5. Объяснение стратегии для UI                                       #
    # ------------------------------------------------------------------ #

    def explain_topic_strategy(
        self, db: Session, project_id: int, platform_key: str | None = None
    ) -> dict[str, Any]:
        """Почему бот советует эти темы; что будет делать чаще / избегать."""
        summary = self.build_project_signal_summary(db, project_id, platform_key)
        will_do_more = list(summary["top_topics"][:5]) + [
            f"#{str(t).lstrip('#')}" for t in summary["high_performing_tags"][:5]
        ]
        will_avoid = list(summary["weak_topics"][:5]) + [
            f"#{str(t).lstrip('#')}" for t in summary["low_performing_tags"][:5]
        ]
        clarify: list[str] = []
        if float(summary.get("confidence_score", 0.0) or 0.0) < 0.3:
            clarify.append("Мало данных — уточните у клиента удачные примеры для калибровки.")
        if not summary["best_cta_patterns"]:
            clarify.append("Нет явного рабочего CTA — стоит протестировать несколько формулировок.")
        return {
            "project_id": project_id,
            "confidence_score": summary.get("confidence_score", 0.0),
            "will_do_more": will_do_more,
            "will_avoid": will_avoid,
            "best_cta": summary["best_cta_patterns"],
            "best_media_types": summary["best_media_types"],
            "best_publish_times": summary["best_publish_times"],
            "clarify": clarify,
        }

    # ------------------------------------------------------------------ #
    # Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    def _recent_usage(self, db: Session, project_id: int) -> Counter[str]:
        """Счётчик недавнего использования тем/тегов (по ПОСЛЕДНИМ постам, id по убыванию)."""
        usage: Counter[str] = Counter()
        recent = post_repository.list_recent_posts(db, project_id, limit=self._recency_window())
        for post in recent:
            if post.title:
                usage[post.title.strip().lower()] += 1
            for tag in post.hashtags or []:
                usage[str(tag).strip().lower().lstrip("#")] += 1
        return usage

    def _content_gaps(
        self, db: Session, project_id: int, summary: dict[str, Any], usage: Counter[str]
    ) -> list[str]:
        """Категории CRM, по которым давно не было постов (best-effort)."""
        gaps: list[str] = []
        config = crm_bot_smm_repository.get_config_by_project_id(db, project_id)
        if config is None:
            return gaps
        for category in crm_bot_smm_repository.list_categories_by_config(db, config.id):
            title = (category.title or "").strip()
            if not title:
                continue
            if usage.get(title.lower(), 0) == 0:
                gaps.append(title)
        return gaps[:10]

    def _experiment_units(self) -> int:
        from app.services.unit_economics_service import UnitEconomicsService

        return UnitEconomicsService(self._settings).estimate_experiment_create_units(
            self._default_variant_count()
        )

    def _recency_window(self) -> int:
        # Приблизительное окно «недавних» постов (по числу, не по дате — стабильно в тестах).
        return 50

    def _max_recommendations(self) -> int:
        return int(getattr(self._resolve_settings(), "topic_optimization_max_recommendations", 10))

    def _default_variant_count(self) -> int:
        return int(getattr(self._resolve_settings(), "ab_testing_default_variant_count", 2))

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _learning_svc(self) -> ClientLearningService:
        if self._learning is None:
            from app.services.client_learning_service import ClientLearningService

            self._learning = ClientLearningService()
        return self._learning

    def _write_audit(
        self, db: Session, project_id: int, action: str, metadata: dict[str, Any]
    ) -> None:
        from app.repositories import project_repository

        project = project_repository.get_project_by_id(db, project_id)
        account_id = project.account_id if project is not None else None
        self._audit_svc().record(
            db,
            action,
            account_id=account_id,
            project_id=project_id,
            entity_type="topic_optimization",
            metadata=metadata,
        )

    def _audit_svc(self) -> AuditLogService:
        if self._audit is None:
            from app.services.audit_log_service import AuditLogService

            self._audit = AuditLogService()
        return self._audit


def _first(values: list[Any]) -> Any:
    return values[0] if values else None


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def get_topic_optimization_service() -> TopicOptimizationService:
    """DI-фабрика сервиса оптимизации тем."""
    return TopicOptimizationService()
