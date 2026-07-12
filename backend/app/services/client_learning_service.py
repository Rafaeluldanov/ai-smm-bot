"""Движок обучения бота на конкретном клиенте (v0.4.0).

Собирает сигналы обратной связи (одобрение / правка / отклонение / оценка) и
метрики аналитики → строит персональный :class:`ClientLearningProfile` проекта и
использует его при следующих генерациях и в блоке «Чему бот научился».

ПРИВАТНОСТЬ / БЕЗОПАСНОСТЬ:
- профиль строго per-project; данные клиента НЕ уходят в глобальное обучение;
- полный текст постов не сохраняется — только hash + агрегированный diff_summary;
- ``event_metadata`` санитизируется (без секретов).

Это не дообучение модели, а безопасный per-client слой эвристик.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.redaction import sanitize_metadata
from app.repositories import (
    analytics_repository,
    client_learning_repository,
    post_feedback_repository,
    post_repository,
    project_repository,
)
from app.services.content_scoring_service import ContentScoringService

if TYPE_CHECKING:
    from app.models.post import Post
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

# Типы событий обратной связи.
EVENT_APPROVED = "approved"
EVENT_REJECTED = "rejected"
EVENT_CHANGES_REQUESTED = "changes_requested"
EVENT_EDITED = "edited"
EVENT_PUBLISHED = "published"
EVENT_MANUAL_RATING = "manual_rating"
EVENT_ANALYTICS_IMPORTED = "analytics_imported"
EVENT_AUTO_PUBLISHED = "auto_published"
EVENT_AUTO_BLOCKED = "auto_blocked"

# Сколько событий даёт «полную» уверенность профиля (confidence → 1.0).
_CONFIDENCE_TARGET_EVENTS = 20
# Порог ER для отнесения тега к сильным/слабым (доля 0..1).
_HIGH_ER = 0.05
_LOW_ER = 0.01


class ClientLearningService:
    """Сбор сигналов и построение профиля обучения клиента."""

    def __init__(
        self,
        scoring_service: ContentScoringService | None = None,
        audit_service: AuditLogService | None = None,
    ) -> None:
        self._scoring = scoring_service or ContentScoringService()
        self._audit = audit_service

    # ------------------------------------------------------------------ #
    # 1. Приём сигналов обратной связи ревью                              #
    # ------------------------------------------------------------------ #

    def record_review_feedback(
        self,
        db: Session,
        post_id: int,
        action: str,
        user_id: int | None = None,
        comment: str | None = None,
        before_text: str | None = None,
        after_text: str | None = None,
        reason_tags: list[str] | None = None,
        rating: int | None = None,
        platform_key: str | None = None,
    ) -> Any:
        """Зафиксировать решение клиента как ``PostFeedbackEvent`` и обновить профиль.

        ``action`` — тип события (approved | rejected | changes_requested | edited |
        published | manual_rating | auto_published | auto_blocked). Возвращает событие.
        """
        post = post_repository.get_post_by_id(db, post_id)
        if post is None:
            raise ValueError(f"Пост id={post_id} не найден")
        account_id = self._account_id(db, post.project_id)
        snapshot = self._content_snapshot(post)

        diff_summary: dict[str, Any] = {}
        before_hash = after_hash = None
        if action == EVENT_EDITED and (before_text is not None or after_text is not None):
            diff_summary = self._analyze_edit(before_text or "", after_text or "")
            before_hash = self._hash(before_text) if before_text is not None else None
            after_hash = self._hash(after_text) if after_text is not None else None

        event = post_feedback_repository.create_event(
            db,
            account_id=account_id,
            project_id=post.project_id,
            post_id=post.id,
            user_id=user_id,
            platform_key=platform_key,
            event_type=action,
            rating=self._clamp_rating(rating),
            reason_tags=list(reason_tags or []),
            before_text_hash=before_hash,
            after_text_hash=after_hash,
            diff_summary=diff_summary,
            metrics_snapshot={},
            event_metadata=self._sanitize({**snapshot, "comment_present": bool(comment)}),
        )
        self._audit_learning(
            db,
            account_id,
            post.project_id,
            user_id,
            "learning.feedback.recorded",
            {
                "post_id": post.id,
                "event_type": action,
            },
        )
        self.build_learning_profile(db, post.project_id, platform_key=None)
        return event

    # ------------------------------------------------------------------ #
    # 2. Приём метрик публикации (аналитика)                              #
    # ------------------------------------------------------------------ #

    def record_publication_performance(
        self,
        db: Session,
        publication_id: int | None,
        metrics: dict[str, Any],
        source: str = "manual",
        post_id: int | None = None,
        project_id: int | None = None,
        platform_key: str | None = None,
        rebuild: bool = True,
    ) -> Any:
        """Зафиксировать импорт метрик как событие ``analytics_imported`` и обновить профиль.

        ``rebuild=False`` — не пересчитывать профиль сразу (для батч-импорта: пересчёт
        делается один раз в конце, чтобы избежать O(n²)).
        """
        from app.repositories import post_publication_repository

        pub = None
        if publication_id is not None:
            pub = post_publication_repository.get_publication_by_id(db, publication_id)
        if pub is not None:
            post_id = pub.post_id
            project_id = pub.project_id
            platform_key = platform_key or pub.platform
        if post_id is None or project_id is None:
            raise ValueError("Нужен publication_id или (post_id, project_id)")
        account_id = self._account_id(db, project_id)
        event = post_feedback_repository.create_event(
            db,
            account_id=account_id,
            project_id=project_id,
            post_id=post_id,
            publication_id=publication_id,
            platform_key=platform_key,
            event_type=EVENT_ANALYTICS_IMPORTED,
            metrics_snapshot=self._sanitize(metrics),
            event_metadata=self._sanitize({"source": source}),
        )
        if rebuild:
            self.build_learning_profile(db, project_id, platform_key=None)
        return event

    # ------------------------------------------------------------------ #
    # 3. Пересчёт профиля из событий + аналитики                          #
    # ------------------------------------------------------------------ #

    def build_learning_profile(
        self, db: Session, project_id: int, platform_key: str | None = None
    ) -> Any:
        """Пересчитать профиль обучения из всех событий и снимков аналитики проекта."""
        account_id = self._account_id(db, project_id)
        events = post_feedback_repository.list_for_project(
            db, project_id, platform_key=platform_key, limit=1000
        )
        snapshots = analytics_repository.list_snapshots_for_project(db, project_id)
        if platform_key is not None:
            snapshots = [s for s in snapshots if s.platform == platform_key]

        derived = self._derive_profile_fields(db, events, snapshots)
        profile = client_learning_repository.upsert_profile(
            db,
            project_id,
            account_id=account_id,
            platform_key=platform_key,
            **derived,
        )
        self._audit_learning(
            db,
            account_id,
            project_id,
            None,
            "learning.profile.updated",
            {"version": profile.profile_version, "events": derived["updated_from_events_count"]},
        )
        return profile

    def rebuild_learning_profile(
        self, db: Session, project_id: int, platform_key: str | None = None
    ) -> Any:
        """Глубокий пересчёт профиля с поднятием версии (платное действие в API)."""
        profile = self.build_learning_profile(db, project_id, platform_key)
        client_learning_repository.increment_version(db, profile)
        account_id = self._account_id(db, project_id)
        self._audit_learning(
            db,
            account_id,
            project_id,
            None,
            "learning.profile.rebuilt",
            {"version": profile.profile_version},
        )
        return profile

    # ------------------------------------------------------------------ #
    # 4. Оценка кандидата контента с учётом профиля                       #
    # ------------------------------------------------------------------ #

    def score_content_candidate(
        self, db: Session, project_id: int, platform_key: str | None, candidate: Any
    ) -> dict[str, Any]:
        """Оценить пост-кандидат: quality/engagement/fit + причины + рекомендации."""
        profile = client_learning_repository.get_profile(db, project_id, platform_key)
        if profile is None:
            profile = client_learning_repository.get_profile(db, project_id, None)
        scored = self._scoring.score_post_against_profile(candidate, profile)
        recommended = self._scoring.recommend_post_improvements(candidate, profile)
        return {
            "quality_score": scored["quality_score"],
            "predicted_engagement_score": scored["predicted_engagement_score"],
            "fit_score": scored["fit_score"],
            "learning_reasons": scored["reasons"],
            "warnings": scored["warnings"],
            "recommended_changes": recommended,
            "profile_version": profile.profile_version if profile is not None else 0,
        }

    # ------------------------------------------------------------------ #
    # 5. Подсказка следующих тем                                          #
    # ------------------------------------------------------------------ #

    def suggest_next_topics(
        self, db: Session, project_id: int, platform_key: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Темы/направления, которые бот будет предлагать чаще (по профилю)."""
        profile = client_learning_repository.get_profile(db, project_id, platform_key)
        if profile is None:
            profile = client_learning_repository.get_profile(db, project_id, None)
        if profile is None:
            return []
        rejected = {str(t).lower() for t in (profile.rejected_topics or [])}
        out: list[dict[str, Any]] = []
        for topic in profile.preferred_topics or []:
            if str(topic).lower() in rejected:
                continue
            out.append({"topic": topic, "reason": "клиент одобрял такие темы"})
        for tag in profile.high_performing_tags or []:
            label = str(tag)
            if label.lower() in rejected:
                continue
            out.append({"topic": f"#{label.lstrip('#')}", "reason": "тег с высоким охватом"})
        # Дедуп по строке темы.
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for item in out:
            key = str(item["topic"]).lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique[:limit]

    def record_suggestion_signal(
        self,
        db: Session,
        project_id: int,
        topic: str,
        positive: bool,
        platform_key: str | None = None,
    ) -> None:
        """Лёгкий сигнал обучения по решению о предложении (accept/reject).

        Не создаёт `PostFeedbackEvent` (у предложения нет поста) — мягко и ограниченно
        двигает профиль: принятая тема → в preferred_topics, отклонённая → в
        rejected_topics (дедуп, кап). Одно отклонение не «перевешивает» (лишь добавляет
        тему в список — вес не накапливается).
        """
        topic = (topic or "").strip()
        if not topic:
            return
        profile = client_learning_repository.get_or_create_profile(
            db, project_id, account_id=self._account_id(db, project_id)
        )
        preferred = list(profile.preferred_topics or [])
        rejected = list(profile.rejected_topics or [])
        lower = topic.lower()
        if positive:
            if all(str(t).lower() != lower for t in preferred):
                preferred = ([topic] + preferred)[:15]
        else:
            if all(str(t).lower() != lower for t in rejected):
                rejected = ([topic] + rejected)[:15]
        client_learning_repository.update_profile_from_signals(
            db, profile, preferred_topics=preferred, rejected_topics=rejected
        )

    # ------------------------------------------------------------------ #
    # 6. Сводка для UI «Чему бот научился»                                #
    # ------------------------------------------------------------------ #

    def summarize_learning(
        self, db: Session, project_id: int, platform_key: str | None = None
    ) -> dict[str, Any]:
        """Компактная сводка профиля для клиента (без секретов)."""
        profile = client_learning_repository.get_profile(db, project_id, platform_key)
        if profile is None:
            profile = client_learning_repository.get_profile(db, project_id, None)
        counts = post_feedback_repository.aggregate_by_project(db, project_id)
        recent = post_feedback_repository.list_for_project(db, project_id, limit=15)
        recent_view = [
            {
                "id": e.id,
                "event_type": e.event_type,
                "post_id": e.post_id,
                "platform_key": e.platform_key,
                "rating": e.rating,
                "reason_tags": list(e.reason_tags or []),
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in recent
        ]
        if profile is None:
            return {
                "project_id": project_id,
                "has_profile": False,
                "confidence_score": 0.0,
                "profile_version": 0,
                "preferred_topics": [],
                "rejected_topics": [],
                "preferred_cta": [],
                "high_performing_tags": [],
                "low_performing_tags": [],
                "preferred_media_types": [],
                "best_publish_times": [],
                "preferred_text_length": {},
                "recommendations": [],
                "approval_patterns": {},
                "editing_patterns": {},
                "performance_patterns": {},
                "event_counts": counts,
                "recent_events": recent_view,
            }
        return {
            "project_id": project_id,
            "platform_key": profile.platform_key,
            "has_profile": True,
            "confidence_score": round(profile.confidence_score, 3),
            "profile_version": profile.profile_version,
            "updated_from_events_count": profile.updated_from_events_count,
            "preferred_topics": list(profile.preferred_topics or []),
            "rejected_topics": list(profile.rejected_topics or []),
            "preferred_cta": list(profile.preferred_cta or []),
            "rejected_cta": list(profile.rejected_cta or []),
            "high_performing_tags": list(profile.high_performing_tags or []),
            "low_performing_tags": list(profile.low_performing_tags or []),
            "preferred_media_types": list(profile.preferred_media_types or []),
            "best_publish_times": list(profile.best_publish_times or []),
            "preferred_text_length": dict(profile.preferred_text_length or {}),
            "brand_voice": dict(profile.brand_voice or {}),
            "recommendations": list(profile.recommendations or []),
            "approval_patterns": dict(profile.approval_patterns or {}),
            "editing_patterns": dict(profile.editing_patterns or {}),
            "performance_patterns": dict(profile.performance_patterns or {}),
            "event_counts": counts,
            "recent_events": recent_view,
            "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
        }

    def explain_learning_changes(
        self, before_profile: Any | None, after_profile: Any | None
    ) -> list[str]:
        """Человеко-читаемые изменения профиля (для блока «как метрики повлияли»).

        ``before``/``after`` — снимки профиля (dict из ``summarize_learning`` или ORM).
        Показывает, что появилось/усилилось/ослабло, без сырых чисел.
        """
        before = self._profile_view(before_profile)
        after = self._profile_view(after_profile)
        changes: list[str] = []

        def _new(field: str, label: str) -> None:
            added = [x for x in after.get(field, []) if x not in set(before.get(field, []))]
            if added:
                changes.append(f"{label}: + {', '.join(str(a) for a in added[:5])}")

        _new("high_performing_tags", "Сильные теги")
        _new("low_performing_tags", "Слабые теги")
        _new("preferred_cta", "Лучший CTA")
        _new("preferred_media_types", "Лучший тип медиа")
        _new("best_publish_times", "Лучшее время")
        _new("preferred_topics", "Темы, которые заходят")

        conf_before = float(before.get("confidence_score", 0) or 0)
        conf_after = float(after.get("confidence_score", 0) or 0)
        if conf_after > conf_before + 0.001:
            changes.append(
                "Уверенность профиля выросла: "
                f"{round(conf_before * 100)}% → {round(conf_after * 100)}%"
            )
        perf = after.get("performance_patterns", {}) or {}
        if perf.get("avg_engagement_rate") is not None:
            changes.append(
                f"Средний ER по метрикам: {round(float(perf['avg_engagement_rate']) * 100, 2)}%"
            )
        if perf.get("useful_content_signals"):
            changes.append("Замечен «полезный» контент (сохранения/репосты) — будем усиливать.")
        if not changes:
            changes.append("Существенных изменений в профиле пока нет — нужно больше метрик.")
        return changes

    @staticmethod
    def _profile_view(profile: Any | None) -> dict[str, Any]:
        """Привести профиль (ORM или dict) к единому dict-снимку для сравнения."""
        if profile is None:
            return {}
        if isinstance(profile, dict):
            return profile
        return {
            "high_performing_tags": list(getattr(profile, "high_performing_tags", []) or []),
            "low_performing_tags": list(getattr(profile, "low_performing_tags", []) or []),
            "preferred_cta": list(getattr(profile, "preferred_cta", []) or []),
            "preferred_media_types": list(getattr(profile, "preferred_media_types", []) or []),
            "best_publish_times": list(getattr(profile, "best_publish_times", []) or []),
            "preferred_topics": list(getattr(profile, "preferred_topics", []) or []),
            "confidence_score": getattr(profile, "confidence_score", 0.0),
            "performance_patterns": dict(getattr(profile, "performance_patterns", {}) or {}),
        }

    # ------------------------------------------------------------------ #
    # Внутреннее: вывод полей профиля из событий/аналитики                #
    # ------------------------------------------------------------------ #

    def _derive_profile_fields(
        self, db: Session, events: list[Any], snapshots: list[Any]
    ) -> dict[str, Any]:
        """Чистая деривация всех обученных полей профиля из событий и метрик."""
        tag_weight: Counter[str] = Counter()
        cta_approved: Counter[str] = Counter()
        cta_rejected: Counter[str] = Counter()
        topics_approved: Counter[str] = Counter()
        topics_rejected: Counter[str] = Counter()
        approved_lengths: list[int] = []
        media_types: Counter[str] = Counter()
        edit_counts: Counter[str] = Counter()
        counts: Counter[str] = Counter()

        for event in events:
            counts[event.event_type] += 1
            meta = event.event_metadata or {}
            hashtags = [str(t) for t in (meta.get("hashtags") or [])]
            cta = str(meta.get("cta") or "").strip()
            title = str(meta.get("title") or "").strip()
            media_type = str(meta.get("media_type") or "").strip()
            length = meta.get("length")

            if event.event_type in (EVENT_APPROVED, EVENT_AUTO_PUBLISHED, EVENT_PUBLISHED):
                for tag in hashtags:
                    tag_weight[_norm_tag(tag)] += 1
                if cta:
                    cta_approved[cta] += 1
                if title:
                    topics_approved[title] += 1
                if isinstance(length, (int, float)) and length > 0:
                    approved_lengths.append(int(length))
                if media_type:
                    media_types[media_type] += 1
            elif event.event_type in (EVENT_REJECTED, EVENT_AUTO_BLOCKED):
                for tag in hashtags:
                    tag_weight[_norm_tag(tag)] -= 1
                if cta:
                    cta_rejected[cta] += 1
                if title:
                    topics_rejected[title] += 1
            elif event.event_type == EVENT_EDITED:
                for key, value in (event.diff_summary or {}).items():
                    if value:
                        edit_counts[key] += 1

        # Аналитика: усиливаем/ослабляем теги/медиа/время по ER, с учётом доверия к
        # источнику метрик (api > manual > internal > estimated > demo).
        er_values: list[float] = []
        ctr_values: list[float] = []
        platform_er: dict[str, list[float]] = {}
        best_hour_weight: Counter[str] = Counter()
        useful_signals = 0
        best_post: tuple[float, int | None] = (-1.0, None)
        worst_post: tuple[float, int | None] = (2.0, None)
        for snap in snapshots:
            er = float(getattr(snap, "engagement_rate", 0.0) or 0.0)
            ctr = float(getattr(snap, "ctr", 0.0) or 0.0)
            source = str(getattr(snap, "source", "demo"))
            confidence = _source_confidence(source)
            er_values.append(er)
            ctr_values.append(ctr)
            platform_er.setdefault(snap.platform, []).append(er)
            post = post_repository.get_post_by_id(db, snap.post_id)
            if post is None:
                continue
            boost = max(1, round(2 * confidence))
            if er >= _HIGH_ER:
                for tag in post.hashtags or []:
                    tag_weight[_norm_tag(str(tag))] += boost
                media_types[self._media_type_for(post)] += 1
                hour = self._publish_hour_for_snapshot(db, snap, post)
                if hour is not None:
                    best_hour_weight[hour] += boost
                if best_post[0] < er:
                    best_post = (er, snap.post_id)
            elif er <= _LOW_ER:
                for tag in post.hashtags or []:
                    tag_weight[_norm_tag(str(tag))] -= boost
                if worst_post[0] > er:
                    worst_post = (er, snap.post_id)
            # «Полезный» контент: высокие сохранения/репосты относительно охвата.
            base = getattr(snap, "reach", 0) or getattr(snap, "impressions", 0) or 0
            useful = (getattr(snap, "saves", 0) or 0) + (getattr(snap, "shares", 0) or 0)
            if base and useful / base >= 0.02:
                useful_signals += 1

        high_tags = [t for t, w in tag_weight.most_common() if w > 0]
        low_tags = [t for t, w in sorted(tag_weight.items(), key=lambda kv: kv[1]) if w < 0]
        best_times = [f"{h}:00" for h, _ in best_hour_weight.most_common(3)]

        approvals = counts[EVENT_APPROVED] + counts[EVENT_AUTO_PUBLISHED]
        rejections = counts[EVENT_REJECTED] + counts[EVENT_AUTO_BLOCKED]
        total_decisions = approvals + rejections + counts[EVENT_CHANGES_REQUESTED]
        approval_rate = round(approvals / total_decisions, 3) if total_decisions else 0.0

        preferred_len: dict[str, Any] = {}
        if approved_lengths:
            approved_lengths.sort()
            median = approved_lengths[len(approved_lengths) // 2]
            preferred_len = {
                "target": int(median),
                "min": approved_lengths[0],
                "max": approved_lengths[-1],
                "samples": len(approved_lengths),
            }

        performance: dict[str, Any] = {}
        if er_values:
            performance["avg_engagement_rate"] = round(sum(er_values) / len(er_values), 4)
            performance["snapshots_count"] = len(er_values)
        if ctr_values:
            performance["avg_ctr"] = round(sum(ctr_values) / len(ctr_values), 4)
        if platform_er:
            best_platform = max(platform_er.items(), key=lambda kv: sum(kv[1]) / len(kv[1]))[0]
            performance["best_platform"] = best_platform
        if best_post[1] is not None:
            performance["best_post_id"] = best_post[1]
            performance["best_post_er"] = round(best_post[0], 4)
        if worst_post[1] is not None:
            performance["worst_post_id"] = worst_post[1]
            performance["worst_post_er"] = round(worst_post[0], 4)
        if useful_signals:
            performance["useful_content_signals"] = useful_signals

        editing_patterns = dict(edit_counts)

        total_events = len(events)
        confidence = round(min(1.0, total_events / _CONFIDENCE_TARGET_EVENTS), 3)

        recommendations = self._build_recommendations(
            high_tags, low_tags, cta_approved, edit_counts, approval_rate, total_events
        )
        brand_voice = self._infer_brand_voice(cta_approved, edit_counts)

        return {
            "brand_voice": brand_voice,
            "preferred_topics": [t for t, _ in topics_approved.most_common(10)],
            "rejected_topics": [t for t, _ in topics_rejected.most_common(10)],
            "preferred_cta": [c for c, _ in cta_approved.most_common(5)],
            "rejected_cta": [c for c, _ in cta_rejected.most_common(5)],
            "preferred_text_length": preferred_len,
            "preferred_media_types": [m for m, _ in media_types.most_common(5)],
            "high_performing_tags": high_tags[:15],
            "low_performing_tags": low_tags[:15],
            "best_publish_times": best_times,
            "approval_patterns": {
                "approved": approvals,
                "rejected": rejections,
                "changes_requested": counts[EVENT_CHANGES_REQUESTED],
                "edited": counts[EVENT_EDITED],
                "auto_published": counts[EVENT_AUTO_PUBLISHED],
                "auto_blocked": counts[EVENT_AUTO_BLOCKED],
                "approval_rate": approval_rate,
            },
            "editing_patterns": editing_patterns,
            "performance_patterns": performance,
            "forbidden_patterns": [c for c, _ in cta_rejected.most_common(3)],
            "recommendations": recommendations,
            "confidence_score": confidence,
            "updated_from_events_count": total_events,
            "status": "active",
        }

    @staticmethod
    def _build_recommendations(
        high_tags: list[str],
        low_tags: list[str],
        cta_approved: Counter[str],
        edit_counts: Counter[str],
        approval_rate: float,
        total_events: int,
    ) -> list[str]:
        """Человеко-читаемые выводы: что бот будет делать чаще/избегать/уточнить."""
        recs: list[str] = []
        if high_tags:
            recs.append(
                f"Будет чаще использовать теги: {', '.join('#' + t for t in high_tags[:5])}."
            )
        if low_tags:
            recs.append(f"Будет избегать слабых тегов: {', '.join('#' + t for t in low_tags[:5])}.")
        if cta_approved:
            top_cta = cta_approved.most_common(1)[0][0]
            recs.append(f"Рабочий призыв к действию клиента: «{top_cta}».")
        if edit_counts.get("shortened"):
            recs.append("Клиент часто сокращает текст — бот будет писать короче.")
        if edit_counts.get("added_cta"):
            recs.append("Клиент часто добавляет CTA — бот будет добавлять его сразу.")
        if edit_counts.get("added_numbers"):
            recs.append("Клиент добавляет цифры/конкретику — бот будет включать факты.")
        if total_events < 5:
            recs.append("Мало данных — уточните у клиента примеры удачных постов.")
        elif approval_rate and approval_rate < 0.5:
            recs.append("Низкая доля одобрений — стоит согласовать тон и офферы.")
        return recs

    @staticmethod
    def _infer_brand_voice(cta_approved: Counter[str], edit_counts: Counter[str]) -> dict[str, Any]:
        """Грубая оценка «голоса бренда» из паттернов правок."""
        voice: dict[str, Any] = {}
        if edit_counts.get("shortened"):
            voice["length_preference"] = "short"
        elif edit_counts.get("lengthened"):
            voice["length_preference"] = "long"
        if edit_counts.get("added_cta"):
            voice["cta"] = "always"
        if cta_approved:
            voice["signature_cta"] = cta_approved.most_common(1)[0][0]
        return voice

    # --- Анализ правок клиента ---

    def _analyze_edit(self, before: str, after: str) -> dict[str, Any]:
        """Что именно поменял клиент: длина / CTA / хэштеги / цифры / тон."""
        bf = self._scoring.analyze_text_features(before)
        af = self._scoring.analyze_text_features(after)
        summary: dict[str, Any] = {}
        if bf["length"] and af["length"] < bf["length"] * 0.85:
            summary["shortened"] = True
        elif bf["length"] and af["length"] > bf["length"] * 1.15:
            summary["lengthened"] = True
        if not bf["has_cta"] and af["has_cta"]:
            summary["added_cta"] = True
        if bf["has_cta"] and not af["has_cta"]:
            summary["removed_cta"] = True
        if af["hashtags_count"] < bf["hashtags_count"]:
            summary["removed_hashtags"] = True
        elif af["hashtags_count"] > bf["hashtags_count"]:
            summary["added_hashtags"] = True
        if not bf["has_numbers"] and af["has_numbers"]:
            summary["added_numbers"] = True
        if bf["tone_markers"] != af["tone_markers"]:
            summary["tone_changed"] = True
        return summary

    # --- Утилиты ---

    def _content_snapshot(self, post: Post) -> dict[str, Any]:
        """Снимок контента поста для события (без полного текста)."""
        text = self._scoring._primary_text(post)
        features = self._scoring.analyze_text_features(text)
        media_type = "with_media" if post.media_asset_id else "text_only"
        notes = post.generation_notes or {}
        if isinstance(notes, dict) and notes.get("media_asset_ids"):
            media_type = "media_group" if len(notes["media_asset_ids"]) > 1 else "with_media"
        return {
            "hashtags": [str(t) for t in (post.hashtags or [])],
            "title": post.title or "",
            "cta": self._extract_cta(post),
            "length": features["length"],
            "has_cta": features["has_cta"],
            "media_type": media_type,
        }

    @staticmethod
    def _extract_cta(post: Post) -> str:
        """Достать CTA из generation_notes, если он там сохранён."""
        notes = post.generation_notes or {}
        if isinstance(notes, dict):
            cta = notes.get("cta") or notes.get("category_cta")
            if cta:
                return str(cta)
        return ""

    @staticmethod
    def _media_type_for(post: Post) -> str:
        """Тип медиа поста для агрегации (text_only | with_media | media_group)."""
        notes = post.generation_notes or {}
        if isinstance(notes, dict) and notes.get("media_asset_ids"):
            return "media_group" if len(notes["media_asset_ids"]) > 1 else "with_media"
        return "with_media" if post.media_asset_id else "text_only"

    @staticmethod
    def _publish_hour_for_snapshot(db: Session, snap: Any, post: Post) -> str | None:
        """Час публикации: публикация (published_at → scheduled_at) → пост. '0'..'23' или None."""
        pub_id = getattr(snap, "post_publication_id", None)
        if pub_id is not None:
            from app.repositories import post_publication_repository

            pub = post_publication_repository.get_publication_by_id(db, pub_id)
            if pub is not None:
                moment = pub.published_at or pub.scheduled_at
                if moment is not None:
                    return str(moment.hour)
        moment = post.published_at or post.scheduled_at
        return str(moment.hour) if moment is not None else None

    @staticmethod
    def _hash(text: str | None) -> str | None:
        if text is None:
            return None
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:64]

    @staticmethod
    def _clamp_rating(rating: int | None) -> int | None:
        if rating is None:
            return None
        return max(1, min(5, int(rating)))

    @staticmethod
    def _sanitize(metadata: dict[str, Any]) -> dict[str, Any]:
        cleaned = sanitize_metadata(metadata)
        return cleaned if isinstance(cleaned, dict) else {}

    @staticmethod
    def _account_id(db: Session, project_id: int) -> int | None:
        project = project_repository.get_project_by_id(db, project_id)
        return project.account_id if project is not None else None

    def _audit_learning(
        self,
        db: Session,
        account_id: int | None,
        project_id: int,
        user_id: int | None,
        action: str,
        metadata: dict[str, Any],
    ) -> None:
        if self._audit is None:
            from app.services.audit_log_service import AuditLogService

            self._audit = AuditLogService()
        self._audit.record(
            db,
            action,
            account_id=account_id,
            user_id=user_id,
            project_id=project_id,
            entity_type="learning_profile",
            metadata=metadata,
        )


def _norm_tag(tag: str) -> str:
    """Нормализовать тег: без ведущей решётки, в нижнем регистре."""
    return tag.strip().lstrip("#").lower()


def _source_confidence(source: str) -> float:
    """Доверие к источнику метрик (api > manual > internal > estimated > demo)."""
    from app.services.metrics_normalization_service import SOURCE_CONFIDENCE

    return SOURCE_CONFIDENCE.get(str(source), 0.2)


def get_client_learning_service() -> ClientLearningService:
    """DI-фабрика движка обучения клиента."""
    return ClientLearningService()
