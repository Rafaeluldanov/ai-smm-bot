"""AILearningService — движок AI Learning Loop (v0.6.5).

Клиентоориентированный слой памяти и обучения ПОВЕРХ существующей аналитики и
:class:`ClientLearningService`. Botfleet учится на конкретном клиенте: анализирует
опубликованные посты, понимает что сработало/не сработало (темы/форматы/стиль/время/
медиа/CTA) и обновляет персональный :class:`AILearningProfile`, который затем
подсказывает следующим публикациям.

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- обучение НЕ публикует и НЕ вызывает внешние API;
- обучение НЕ включает и НЕ меняет глобальные live-флаги;
- обучение НЕ меняет стратегию автоматически — только строит рекомендации;
- каждое изменение профиля пишется в AuditLog;
- reset НЕ удаляет историю сигналов (события сохраняются);
- секретов/токенов не хранит (event_metadata санитизируется).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.core.redaction import sanitize_metadata
from app.repositories import (
    ai_learning_repository as repo,
)
from app.repositories import (
    analytics_repository,
    post_repository,
    project_repository,
    topic_repository,
)
from app.services import analytics_metrics
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.ai_learning_profile import AILearningProfile
    from app.models.post import Post
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)


def _aware(value: datetime | None) -> datetime | None:
    """Привести datetime к aware UTC (SQLite может вернуть naive)."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


# Метрика снапшота → тип сигнала обучения.
_METRIC_TO_SIGNAL: dict[str, str] = {
    "impressions": "impression",
    "likes": "like",
    "comments": "comment",
    "shares": "share",
    "saves": "save",
    "clicks": "click",
}
# Клиентский sentiment → (event_type, value, rating).
_FEEDBACK_SENTIMENT: dict[str, tuple[str, float, int]] = {
    "excellent": ("client_rating", 1.0, 5),
    "good": ("client_rating", 0.6, 4),
    "ok": ("client_rating", 0.2, 3),
    "bad": ("client_rating", -1.0, 1),
}
# Сколько «сигналов» дают полную уверенность (learning_score → 100).
_CONFIDENCE_TARGET = 20
# Порог learning_score, при котором профиль считается стабильным.
_STABLE_SCORE = 70.0
# Верхняя граница «хорошего» перф-скора для отнесения в preferred.
_GOOD_SCORE = 55.0
_WEAK_SCORE = 25.0


class AILearningError(Exception):
    """Ошибка AI-обучения (нет проекта/поста) — API → 400/404."""


class AILearningService:
    """Память + обучение per-client (live не включает, ничего не публикует)."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Профиль                                                            #
    # ------------------------------------------------------------------ #

    def get_or_create_profile(self, db: Session, project_id: int) -> AILearningProfile:
        """Создать/получить профиль обучения проекта."""
        self._require_project(db, project_id)
        return repo.get_or_create_profile(
            db, project_id, account_id=self._account_id(db, project_id)
        )

    def get_summary(self, db: Session, project_id: int) -> dict[str, Any]:
        """Сводка профиля для клиента/UI (без секретов)."""
        profile = self.get_or_create_profile(db, project_id)
        return repo.build_learning_summary(db, profile)

    # ------------------------------------------------------------------ #
    # Приём событий                                                      #
    # ------------------------------------------------------------------ #

    def record_event(
        self,
        db: Session,
        project_id: int,
        *,
        entity: str,
        event: str,
        value: float = 0.0,
        source: str = "system",
        entity_id: int | None = None,
        metadata: dict[str, Any] | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Записать единичный сигнал обучения (без секретов, без публикаций)."""
        self._require_project(db, project_id)
        row = repo.add_event(
            db,
            project_id=project_id,
            account_id=self._account_id(db, project_id),
            entity_type=entity,
            entity_id=entity_id,
            event_type=event,
            value=float(value or 0.0),
            source=source,
            event_metadata=self._sanitize(metadata or {}),
        )
        # Клиентские/ручные сигналы — счётчик обратной связи в профиле.
        if source in ("client", "ai"):
            profile = repo.get_or_create_profile(
                db, project_id, account_id=self._account_id(db, project_id)
            )
            repo.update_profile(
                db, profile, total_feedback_events=profile.total_feedback_events + 1
            )
        self._write_audit(
            db,
            audit_actions.ACTION_AI_LEARNING_EVENT_RECORDED,
            project_id,
            user_id,
            {"entity": entity, "event": event, "source": source},
        )
        return repo.public_event_view(row)

    def record_client_feedback(
        self,
        db: Session,
        project_id: int,
        *,
        sentiment: str | None = None,
        rating: int | None = None,
        post_id: int | None = None,
        comment_present: bool = False,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Клиентский фидбэк по посту («Как вам пост?») → сигнал обучения.

        Принимает ``sentiment`` (excellent|good|ok|bad) ИЛИ ``rating`` (1..5). Никаких
        секретов/полного текста — только агрегированный сигнал.
        """
        event_type = "manual_feedback"
        value = 0.0
        norm_rating = self._clamp_rating(rating)
        if sentiment:
            mapped = _FEEDBACK_SENTIMENT.get(str(sentiment).strip().lower())
            if mapped is None:
                raise AILearningError("Неизвестная оценка поста")
            event_type, value, norm_rating = mapped
        elif norm_rating is not None:
            event_type = "client_rating"
            value = round((norm_rating - 3) / 2.0, 3)  # 1..5 → -1..+1
        else:
            raise AILearningError("Нужна оценка (sentiment или rating)")
        meta: dict[str, Any] = {"comment_present": bool(comment_present)}
        if norm_rating is not None:
            meta["rating"] = norm_rating
        return self.record_event(
            db,
            project_id,
            entity="post",
            event=event_type,
            value=value,
            source="client",
            entity_id=post_id,
            metadata=meta,
            user_id=user_id,
        )

    # ------------------------------------------------------------------ #
    # Анализ производительности постов                                   #
    # ------------------------------------------------------------------ #

    def analyze_post_performance(self, db: Session, post_id: int) -> dict[str, Any]:
        """Разобрать метрики поста в сигналы обучения (идемпотентно, без дублей).

        Берёт снапшоты аналитики поста, суммирует ключевые метрики и создаёт
        ``AILearningEvent`` (source=analytics) — по одному на метрику, только если
        значение изменилось относительно последнего события того же типа.
        """
        post = post_repository.get_post_by_id(db, post_id)
        if post is None:
            raise AILearningError(f"Пост id={post_id} не найден")
        project_id = post.project_id
        account_id = self._account_id(db, project_id)
        snaps = analytics_repository.list_snapshots(db, post_id=post_id, limit=500)
        metrics = self._aggregate_metrics(snaps)
        events_created = 0
        for metric_key, signal in _METRIC_TO_SIGNAL.items():
            metric_value = float(metrics.get(metric_key, 0) or 0)
            if metric_value <= 0:
                continue
            latest = repo.get_latest_event(
                db, project_id, entity_type="post", entity_id=post_id, event_type=signal
            )
            if latest is not None and float(latest.value or 0.0) == metric_value:
                continue  # без изменений — не плодим дубли (историю не удаляем)
            repo.add_event(
                db,
                project_id=project_id,
                account_id=account_id,
                entity_type="post",
                entity_id=post_id,
                event_type=signal,
                value=metric_value,
                source="analytics",
                event_metadata={
                    "format": self._post_format(post),
                    "media_type": self._media_type(post),
                    "topic_id": post.topic_id,
                },
            )
            events_created += 1
        return {
            "post_id": post_id,
            "project_id": project_id,
            "metrics": metrics,
            "events_created": events_created,
        }

    def analyze_project(
        self,
        db: Session,
        project_id: int,
        *,
        window_days: int | None = None,
        max_posts: int = 200,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Полный проход: собрать сигналы по недавним постам + пересчитать профиль."""
        self._require_project(db, project_id)
        posts = post_repository.list_recent_posts(db, project_id, limit=max_posts)
        analyzed = 0
        for post in posts:
            try:
                res = self.analyze_post_performance(db, post.id)
                if res["metrics"].get("snapshots", 0) > 0:
                    analyzed += 1
            except AILearningError:
                continue
        summary = self.update_client_learning(
            db, project_id, window_days=window_days, user_id=user_id
        )
        summary["posts_scanned"] = len(posts)
        summary["posts_with_metrics"] = analyzed
        return summary

    # ------------------------------------------------------------------ #
    # Главный алгоритм обучения                                          #
    # ------------------------------------------------------------------ #

    def update_client_learning(
        self,
        db: Session,
        project_id: int,
        *,
        window_days: int | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Пересчитать профиль обучения из аналитики + событий за окно (30/60/90 дней)."""
        self._require_project(db, project_id)
        profile = repo.get_or_create_profile(
            db, project_id, account_id=self._account_id(db, project_id)
        )
        settings = self._resolve_settings()
        if not settings.ai_learning_enabled_effective:
            # Kill-switch: обучение отключено — профиль не пересчитываем.
            return repo.build_learning_summary(db, profile)
        if profile.status == "paused":
            # На паузе обучение заморожено (safety): не пересчитываем.
            return repo.build_learning_summary(db, profile)

        window = (
            window_days
            if window_days is not None
            else settings.ai_learning_default_window_days_safe
        )
        since = self._since(window)
        snapshots = [
            s
            for s in analytics_repository.list_snapshots_for_project(db, project_id)
            if _aware(s.snapshot_at) is None or _aware(s.snapshot_at) >= since  # type: ignore[operator]
        ]
        events = repo.list_events(db, project_id, since=since, limit=5000)
        derived = self._compute_profile_fields(db, project_id, snapshots, events)

        repo.update_profile(
            db,
            profile,
            last_learning_at=datetime.now(UTC),
            **derived,
        )
        self._write_audit(
            db,
            audit_actions.ACTION_AI_LEARNING_PROFILE_UPDATED,
            project_id,
            user_id,
            {
                "learning_score": derived["learning_score"],
                "status": derived["status"],
                "posts_analyzed": derived["total_posts_analyzed"],
                "window_days": window,
            },
        )
        return repo.build_learning_summary(db, profile)

    # ------------------------------------------------------------------ #
    # Рекомендации / объяснение                                          #
    # ------------------------------------------------------------------ #

    def recommend_next_content(self, db: Session, project_id: int) -> dict[str, Any]:
        """Рекомендации для следующей публикации (НЕ применяются автоматически)."""
        profile = self.get_or_create_profile(db, project_id)
        topics = list(profile.preferred_topics or [])
        formats = list(profile.preferred_formats or [])
        styles = list(profile.preferred_styles or [])
        times = list(profile.best_publish_times or [])
        # Дополняем существующим движком обучения (reuse, не дублируем).
        if not topics:
            topics = self._fallback_topics(db, project_id)
        best_time = times[0] if times else ""
        return {
            "project_id": project_id,
            "recommended_topics": topics[:5],
            "recommended_formats": formats[:3],
            "recommended_style": styles[0] if styles else "",
            "best_time": best_time,
            "avoid_topics": list(profile.avoided_topics or [])[:5],
            "confidence": round(float(profile.learning_score or 0.0), 1),
            "note": "Рекомендации не применяются автоматически — стратегию меняете вы.",
        }

    def explain_learning(self, db: Session, project_id: int) -> dict[str, Any]:
        """Клиентское объяснение: что Botfleet понял и что улучшилось."""
        profile = self.get_or_create_profile(db, project_id)
        understood: list[str] = []
        if profile.preferred_topics:
            understood.append(
                "Лучше всего заходят темы: "
                + ", ".join(str(t) for t in profile.preferred_topics[:3])
            )
        if profile.preferred_formats:
            understood.append(
                "Сильные форматы: " + ", ".join(str(f) for f in profile.preferred_formats[:3])
            )
        if profile.preferred_styles:
            understood.append("Лучший стиль: " + str(profile.preferred_styles[0]))
        if profile.best_publish_times:
            understood.append(
                "Лучшее время публикаций: " + ", ".join(profile.best_publish_times[:3])
            )
        if profile.best_platforms:
            understood.append("Сильнее работает площадка: " + str(profile.best_platforms[0]))
        media_best = (profile.media_preferences or {}).get("best_media_type")
        if media_best:
            understood.append("Тип медиа с лучшим откликом: " + self._media_label(media_best))
        if not understood:
            understood.append(
                "Пока мало данных. Публикуйте посты и импортируйте метрики — обучение начнётся."
            )
        improvements = self._improvement_notes(profile)
        return {
            "project_id": project_id,
            "status": profile.status,
            "learning_score": round(float(profile.learning_score or 0.0), 1),
            "confidence_level": self._confidence_level(profile.learning_score),
            "understood": understood,
            "improvements": improvements,
            "recommendations": list((profile.content_rules or {}).get("recommendations", [])),
        }

    # ------------------------------------------------------------------ #
    # Reset (без удаления истории событий)                               #
    # ------------------------------------------------------------------ #

    def reset_learning(
        self, db: Session, project_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Сбросить агрегаты профиля (историю сигналов НЕ удаляем)."""
        profile = self.get_or_create_profile(db, project_id)
        repo.update_profile(
            db,
            profile,
            status="learning",
            learning_score=0.0,
            total_posts_analyzed=0,
            total_feedback_events=0,
            preferred_topics=[],
            avoided_topics=[],
            preferred_formats=[],
            avoided_formats=[],
            preferred_styles=[],
            best_publish_times=[],
            best_platforms=[],
            content_rules={},
            media_preferences={},
            cta_preferences={},
            last_learning_at=None,
        )
        self._write_audit(
            db,
            audit_actions.ACTION_AI_LEARNING_RESET,
            project_id,
            user_id,
            {"events_preserved": repo.count_events(db, project_id)},
        )
        return repo.build_learning_summary(db, profile)

    # ------------------------------------------------------------------ #
    # Внутреннее: агрегация и деривация                                  #
    # ------------------------------------------------------------------ #

    def _compute_profile_fields(
        self, db: Session, project_id: int, snapshots: list[Any], events: list[Any]
    ) -> dict[str, Any]:
        """Чистая деривация всех обученных полей профиля из метрик + событий."""
        # Последний снапшот на (post, platform), чтобы не считать один пост дважды.
        latest: dict[tuple[int, str], Any] = {}
        for snap in snapshots:
            key = (snap.post_id, snap.platform)
            prev = latest.get(key)
            if prev is None or (snap.id or 0) > (prev.id or 0):
                latest[key] = snap

        per_post: dict[int, dict[str, Any]] = {}
        platform_scores: dict[str, list[float]] = defaultdict(list)
        for snap in latest.values():
            post = post_repository.get_post_by_id(db, snap.post_id)
            if post is None:
                continue
            engagements = analytics_metrics.calculate_engagements(
                snap.likes or 0,
                snap.reactions or 0,
                snap.comments or 0,
                snap.shares or 0,
                snap.saves or 0,
            )
            score = analytics_metrics.calculate_performance_score(
                snap.impressions or 0,
                snap.reach or 0,
                engagements,
                snap.clicks or 0,
                float(snap.ctr or 0.0),
                float(snap.engagement_rate or 0.0),
            )
            entry = per_post.setdefault(
                snap.post_id,
                {
                    "post": post,
                    "scores": [],
                    "saves": 0,
                    "shares": 0,
                    "base": 0,
                    "platforms": set(),
                },
            )
            entry["scores"].append(score)
            entry["saves"] += snap.saves or 0
            entry["shares"] += snap.shares or 0
            entry["base"] += max(snap.reach or 0, snap.impressions or 0)
            entry["platforms"].add(snap.platform)

        # Клиентские сигналы (rating/feedback) → бонус/штраф баллов посту.
        feedback_bonus: dict[int, float] = defaultdict(float)
        feedback_events = 0
        for ev in events:
            if ev.source == "client" and ev.entity_type == "post" and ev.entity_id is not None:
                feedback_bonus[ev.entity_id] += float(ev.value or 0.0) * 15.0
                feedback_events += 1

        format_scores: dict[str, list[float]] = defaultdict(list)
        topic_scores: dict[str, list[float]] = defaultdict(list)
        media_scores: dict[str, list[float]] = defaultdict(list)
        hour_scores: dict[str, list[float]] = defaultdict(list)
        style_lengths: list[int] = []
        adjusted_scores: list[float] = []
        useful_signals = 0

        for post_id, entry in per_post.items():
            post = entry["post"]
            base_score = sum(entry["scores"]) / len(entry["scores"])
            # Единый feedback-скорректированный балл поста — используем ВЕЗДЕ (форматы/темы/
            # медиа/время/площадки/среднее), чтобы клиентский вывод был согласован.
            score = max(0.0, min(100.0, base_score + feedback_bonus.get(post_id, 0.0)))
            adjusted_scores.append(score)
            fmt = self._post_format(post)
            media = self._media_type(post)
            topic = self._topic_label(db, post)
            hour = self._publish_hour(post)
            format_scores[fmt].append(score)
            media_scores[media].append(score)
            for platform in entry["platforms"]:
                platform_scores[platform].append(score)
            if topic:
                topic_scores[topic].append(score)
            if hour is not None:
                hour_scores[hour].append(score)
            if score >= _GOOD_SCORE:
                style_lengths.append(self._text_length(post))
            if entry["base"] and (entry["saves"] + entry["shares"]) / entry["base"] >= 0.02:
                useful_signals += 1

        preferred_topics, avoided_topics = self._split_by_score(topic_scores)
        preferred_formats, avoided_formats = self._split_by_score(format_scores)
        best_platforms = [
            p
            for p, _ in sorted(
                ((p, sum(v) / len(v)) for p, v in platform_scores.items()),
                key=lambda kv: kv[1],
                reverse=True,
            )
        ]
        best_times = [
            f"{h}:00"
            for h, _ in sorted(
                ((h, sum(v) / len(v)) for h, v in hour_scores.items()),
                key=lambda kv: kv[1],
                reverse=True,
            )[:3]
        ]
        media_preferences = self._media_preferences(media_scores, useful_signals)
        preferred_styles = self._styles(style_lengths)
        cta_preferences = self._cta_preferences(db, project_id)

        total_posts = len(per_post)
        signals = total_posts + feedback_events
        learning_score = round(min(100.0, 100.0 * signals / _CONFIDENCE_TARGET), 1)
        status = "stable" if learning_score >= _STABLE_SCORE else "learning"

        recommendations = self._recommendations(
            preferred_formats, preferred_topics, avoided_formats, useful_signals, total_posts
        )
        content_rules = {
            "recommendations": recommendations,
            "useful_content_signals": useful_signals,
            "avg_performance": (
                round(sum(adjusted_scores) / len(adjusted_scores), 1) if adjusted_scores else 0.0
            ),
        }

        return {
            "status": status,
            "learning_score": learning_score,
            "total_posts_analyzed": total_posts,
            "total_feedback_events": feedback_events,
            "preferred_topics": preferred_topics[:8],
            "avoided_topics": avoided_topics[:8],
            "preferred_formats": preferred_formats[:5],
            "avoided_formats": avoided_formats[:5],
            "preferred_styles": preferred_styles,
            "best_publish_times": best_times,
            "best_platforms": best_platforms[:3],
            "content_rules": content_rules,
            "media_preferences": media_preferences,
            "cta_preferences": cta_preferences,
        }

    @staticmethod
    def _split_by_score(scores: dict[str, list[float]]) -> tuple[list[str], list[str]]:
        """Разбить измерения на сильные (>= _GOOD) и слабые (<= _WEAK) по среднему баллу."""
        ranked = sorted(
            ((k, sum(v) / len(v)) for k, v in scores.items() if v),
            key=lambda kv: kv[1],
            reverse=True,
        )
        preferred = [k for k, avg in ranked if avg >= _GOOD_SCORE]
        avoided = [k for k, avg in ranked if avg <= _WEAK_SCORE]
        return preferred, avoided

    @staticmethod
    def _media_preferences(
        media_scores: dict[str, list[float]], useful_signals: int
    ) -> dict[str, Any]:
        if not media_scores:
            return {}
        ranked = sorted(
            ((k, round(sum(v) / len(v), 1)) for k, v in media_scores.items()),
            key=lambda kv: kv[1],
            reverse=True,
        )
        return {
            "best_media_type": ranked[0][0],
            "scores": dict(ranked),
            "useful_content_signals": useful_signals,
        }

    @staticmethod
    def _styles(style_lengths: list[int]) -> list[str]:
        if not style_lengths:
            return []
        avg = sum(style_lengths) / len(style_lengths)
        if avg >= 600:
            return ["подробный"]
        if avg <= 250:
            return ["короткий"]
        return ["средний"]

    def _cta_preferences(self, db: Session, project_id: int) -> dict[str, Any]:
        """CTA-предпочтения: усиливаем существующим движком обучения, если он что-то знает."""
        try:
            from app.repositories import client_learning_repository

            profile = client_learning_repository.get_profile(db, project_id)
        except Exception:  # noqa: BLE001 — вспомогательный источник не критичен
            profile = None
        if profile is None:
            return {}
        preferred = list(getattr(profile, "preferred_cta", []) or [])
        rejected = list(getattr(profile, "rejected_cta", []) or [])
        out: dict[str, Any] = {}
        if preferred:
            out["preferred"] = preferred[:5]
        if rejected:
            out["avoid"] = rejected[:5]
        return out

    def _fallback_topics(self, db: Session, project_id: int) -> list[str]:
        """Если профиль пуст — берём подсказки существующего ClientLearningService."""
        try:
            from app.services.client_learning_service import ClientLearningService

            suggestions = ClientLearningService().suggest_next_topics(db, project_id, limit=5)
            return [str(s.get("topic")) for s in suggestions if s.get("topic")]
        except Exception:  # noqa: BLE001 — вспомогательный источник не критичен
            return []

    @staticmethod
    def _recommendations(
        preferred_formats: list[str],
        preferred_topics: list[str],
        avoided_formats: list[str],
        useful_signals: int,
        total_posts: int,
    ) -> list[str]:
        recs: list[str] = []
        if preferred_formats:
            recs.append("Делать больше постов в форматах: " + ", ".join(preferred_formats[:3]))
        if preferred_topics:
            recs.append("Усилить темы: " + ", ".join(str(t) for t in preferred_topics[:3]))
        if avoided_formats:
            recs.append("Реже использовать форматы: " + ", ".join(avoided_formats[:3]))
        if useful_signals:
            recs.append("Контент с сохранениями/репостами заходит — добавить пользы/фактуры.")
        if total_posts < 3:
            recs.append("Мало данных — опубликуйте больше постов и импортируйте метрики.")
        return recs

    def _improvement_notes(self, profile: AILearningProfile) -> list[str]:
        """Клиентские заметки об улучшениях (по content_rules, без сырых чисел там где можно)."""
        notes: list[str] = []
        rules = profile.content_rules or {}
        if rules.get("avg_performance"):
            notes.append(f"Средняя эффективность постов: {rules['avg_performance']} из 100")
        if rules.get("useful_content_signals"):
            notes.append(f"Постов с высоким «полезным» откликом: {rules['useful_content_signals']}")
        if profile.total_posts_analyzed:
            notes.append(f"Проанализировано постов: {profile.total_posts_analyzed}")
        if not notes:
            notes.append("Накопим больше метрик — покажем динамику улучшений.")
        return notes

    # --- утилиты полей поста ---

    @staticmethod
    def _post_format(post: Post) -> str:
        notes = post.generation_notes or {}
        if isinstance(notes, dict):
            fmt = notes.get("selected_format") or notes.get("format")
            if fmt:
                return str(fmt)
        return "unknown"

    @staticmethod
    def _media_type(post: Post) -> str:
        notes = post.generation_notes or {}
        if isinstance(notes, dict) and notes.get("media_asset_ids"):
            return "media_group" if len(notes["media_asset_ids"]) > 1 else "with_media"
        return "with_media" if post.media_asset_id else "text_only"

    @staticmethod
    def _media_label(media_type: str) -> str:
        return {
            "with_media": "фото/медиа",
            "media_group": "галерея из нескольких фото",
            "text_only": "только текст",
        }.get(media_type, media_type)

    @staticmethod
    def _topic_label(db: Session, post: Post) -> str:
        if post.topic_id is not None:
            topic = topic_repository.get_topic_by_id(db, post.topic_id)
            if topic is not None and topic.title:
                return str(topic.title)
        if post.title:
            return str(post.title)
        return ""

    @staticmethod
    def _publish_hour(post: Post) -> str | None:
        moment = post.published_at or post.scheduled_at
        return str(moment.hour) if moment is not None else None

    @staticmethod
    def _text_length(post: Post) -> int:
        for field in ("vk_text", "telegram_text", "instagram_text"):
            text = getattr(post, field, None)
            if text:
                return len(str(text))
        return 0

    @staticmethod
    def _aggregate_metrics(snapshots: list[Any]) -> dict[str, Any]:
        """Суммировать метрики поста по последним снапшотам каждой площадки."""
        latest: dict[str, Any] = {}
        for snap in snapshots:
            prev = latest.get(snap.platform)
            if prev is None or (snap.id or 0) > (prev.id or 0):
                latest[snap.platform] = snap
        agg = {
            "impressions": 0,
            "reach": 0,
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "saves": 0,
            "clicks": 0,
            "snapshots": len(latest),
        }
        for snap in latest.values():
            for key in ("impressions", "reach", "likes", "comments", "shares", "saves", "clicks"):
                agg[key] += int(getattr(snap, key, 0) or 0)
        return agg

    @staticmethod
    def _confidence_level(score: float | None) -> str:
        value = float(score or 0.0)
        if value >= _STABLE_SCORE:
            return "high"
        if value >= 35.0:
            return "medium"
        return "low"

    # --- инфраструктура ---

    @staticmethod
    def _since(window_days: int) -> datetime:
        days = max(1, min(int(window_days or 90), 365))
        return datetime.now(UTC) - timedelta(days=days)

    @staticmethod
    def _clamp_rating(rating: int | None) -> int | None:
        if rating is None:
            return None
        return max(1, min(5, int(rating)))

    @staticmethod
    def _sanitize(metadata: dict[str, Any]) -> dict[str, Any]:
        cleaned = sanitize_metadata(metadata)
        return cleaned if isinstance(cleaned, dict) else {}

    def _require_project(self, db: Session, project_id: int) -> Any:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise AILearningError(f"Проект id={project_id} не найден")
        return project

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
            entity_type="ai_learning_profile",
            metadata=metadata,
        )


def get_ai_learning_service() -> AILearningService:
    """DI-фабрика движка AI-обучения."""
    return AILearningService()
