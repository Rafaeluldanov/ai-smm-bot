"""Сервис выбора тем и формирования недельного контент-плана.

Бот сам выбирает темы: человек задаёт лишь стратегические направления
(business_priorities). Темы берутся из ``topic_taxonomy``, оцениваются по
рыночным сигналам (``market_signal_provider``) и готовности медиа, сохраняются
в таблицу ``topics`` и раскладываются в недельный план. Готовые посты НЕ
создаются на этом этапе.
"""

from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.repositories import media_asset_repository, project_repository, topic_repository
from app.schemas.topic import (
    ContentPlanItem,
    TopicCandidateRead,
    TopicSelectionRequest,
    TopicSelectionResult,
    WeeklyContentPlan,
)
from app.services import topic_taxonomy
from app.services.market_signal_provider import BaseMarketSignalProvider
from app.services.media_analysis_service import MediaAnalysisService
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError

logger = get_logger(__name__)

# Готовность медиа по статусу актива.
_STATUS_READINESS: dict[str, float] = {
    "approved": 1.0,
    "approved_video": 1.0,
    "new": 0.6,
    "needs_reshoot": 0.3,
}

# День публикации по номеру слота в неделе.
_SLOT_DAYS: dict[int, str] = {
    1: "Понедельник",
    2: "Среда",
    3: "Пятница",
    4: "Вторник",
    5: "Четверг",
    6: "Суббота",
    7: "Воскресенье",
}


class TopicSelectionService:
    """Выбирает темы для проекта и строит недельный контент-план."""

    def __init__(
        self,
        market_provider: BaseMarketSignalProvider,
        media_analysis_service: MediaAnalysisService,
    ) -> None:
        self._market = market_provider
        self._media_analysis = media_analysis_service

    # --- Публичные методы выбора тем ---

    def select_topics_for_project(
        self, db: Session, project_id: int, request: TopicSelectionRequest | None = None
    ) -> TopicSelectionResult:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)
        return self._select(db, project.id, project.slug, request or TopicSelectionRequest())

    def select_topics_for_project_slug(
        self, db: Session, slug: str, request: TopicSelectionRequest | None = None
    ) -> TopicSelectionResult:
        project = project_repository.get_project_by_slug(db, slug)
        if project is None:
            raise ProjectNotFoundError(slug)
        return self._select(db, project.id, project.slug, request or TopicSelectionRequest())

    def build_weekly_content_plan(
        self, db: Session, project_id: int, request: TopicSelectionRequest | None = None
    ) -> WeeklyContentPlan:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)
        return self._plan(db, project.id, project.slug, request or TopicSelectionRequest())

    def build_weekly_content_plan_by_slug(
        self, db: Session, slug: str, request: TopicSelectionRequest | None = None
    ) -> WeeklyContentPlan:
        project = project_repository.get_project_by_slug(db, slug)
        if project is None:
            raise ProjectNotFoundError(slug)
        return self._plan(db, project.id, project.slug, request or TopicSelectionRequest())

    # --- Скоринг ---

    def score_topic_candidate(
        self,
        project_slug: str,
        candidate: dict[str, Any],
        tag_summary: dict[str, Any],
        business_priorities: dict[str, int] | None,
    ) -> dict[str, Any]:
        """Оценить кандидата-тему. ``tag_summary`` — медиа-контекст проекта.

        Формула priority_score (0..100):
        search_demand*25 + commercial_intent*25 + trend*10 + seasonality*10 +
        media_readiness*15 + business_priority*20 − competition*5.
        """
        signals = self._market.get_signals(project_slug, candidate["title"], candidate["cluster"])
        search_demand = signals["search_demand_score"]
        commercial_intent = signals["commercial_intent_score"]
        seasonality = signals["seasonality_score"]
        trend = signals["trend_score"]
        competition = signals["competition_score"]

        media_readiness = self._media_readiness_score(candidate["related_media_tags"], tag_summary)
        bp_score, bp_value = self._business_priority(candidate, business_priorities)

        raw = (
            search_demand * 25
            + commercial_intent * 25
            + trend * 10
            + seasonality * 10
            + media_readiness * 15
            + bp_score * 20
            - competition * 5
        )
        priority_score = round(max(0.0, min(100.0, raw)), 2)

        seo_keywords = list(
            dict.fromkeys(
                [
                    *candidate["base_seo_keywords"],
                    *signals["seo_keywords"],
                    topic_taxonomy.normalize_topic_key(candidate["title"]),
                ]
            )
        )
        explanation = self._build_explanation(
            candidate,
            commercial_intent,
            search_demand,
            media_readiness,
            bp_score,
            business_priorities,
        )

        return {
            "title": candidate["title"],
            "cluster": candidate["cluster"],
            "priority_score": priority_score,
            "business_priority": bp_value,
            "media_readiness_score": round(media_readiness, 2),
            "search_demand_score": search_demand,
            "commercial_intent_score": commercial_intent,
            "seasonality_score": seasonality,
            "trend_score": trend,
            "competition_score": competition,
            "seo_keywords": seo_keywords,
            "recommended_formats": list(candidate["recommended_formats"]),
            "related_media_tags": list(candidate["related_media_tags"]),
            "explanation": explanation,
            "status": "candidate",
        }

    # --- Внутренняя логика ---

    def _select(
        self, db: Session, project_id: int, project_slug: str, request: TopicSelectionRequest
    ) -> TopicSelectionResult:
        warnings: list[str] = []
        candidates = topic_taxonomy.get_all_topic_candidates(project_slug)
        if not candidates:
            warnings.append(f"Проект '{project_slug}' не найден в словаре тем — кандидатов нет")

        business = request.business_priorities
        if not business:
            warnings.append("business_priorities не заданы — использованы дефолтные приоритеты")

        media_context = self._build_media_context(db, project_id)
        if media_context["approved_count"] == 0:
            warnings.append("Мало одобренных медиа: рекомендуется досъёмка и одобрение фото")

        scored = [
            self.score_topic_candidate(project_slug, candidate, media_context, business)
            for candidate in candidates
        ]
        scored.sort(key=lambda s: (s["priority_score"], s["media_readiness_score"]), reverse=True)
        if not request.include_low_media_readiness:
            with_media = [s for s in scored if s["media_readiness_score"] > 0]
            without_media = [s for s in scored if s["media_readiness_score"] == 0]
            ordered = with_media + without_media
        else:
            ordered = scored

        target = max(
            request.posts_per_week * request.weeks * 2, request.posts_per_week * request.weeks
        )
        selected = ordered[:target]

        created = 0
        updated = 0
        for item in selected:
            item["status"] = "recommended"
            _topic, action = topic_repository.upsert_topic_candidate(db, project_id, item)
            if action == "created":
                created += 1
            elif action == "updated":
                updated += 1

        if len(selected) < request.posts_per_week * request.weeks:
            warnings.append("Выбрано тем меньше, чем требуется публикаций в плане")

        return TopicSelectionResult(
            project_id=project_id,
            project_slug=project_slug,
            selected_count=len(selected),
            candidates_count=len(scored),
            created=created,
            updated=updated,
            topics=[TopicCandidateRead(**item) for item in selected],
            warnings=warnings,
        )

    def _plan(
        self, db: Session, project_id: int, project_slug: str, request: TopicSelectionRequest
    ) -> WeeklyContentPlan:
        warnings: list[str] = []
        recommended = topic_repository.list_topics(
            db, project_id=project_id, status="recommended", limit=1000
        )
        if not recommended:
            self._select(db, project_id, project_slug, request)
            recommended = topic_repository.list_topics(
                db, project_id=project_id, status="recommended", limit=1000
            )

        media_context = self._build_media_context(db, project_id)
        scored_by_title = {
            topic_taxonomy.normalize_topic_key(item["title"]): item
            for item in (
                self.score_topic_candidate(
                    project_slug, candidate, media_context, request.business_priorities
                )
                for candidate in topic_taxonomy.get_all_topic_candidates(project_slug)
            )
        }

        need = request.posts_per_week * request.weeks
        chosen = recommended[:need]
        if len(chosen) < need:
            warnings.append("Недостаточно рекомендованных тем для полного плана")

        items: list[ContentPlanItem] = []
        for index, topic in enumerate(chosen):
            week_number = index // request.posts_per_week + 1
            slot_number = index % request.posts_per_week + 1
            scored = scored_by_title.get(topic_taxonomy.normalize_topic_key(topic.title))
            recommended_formats = scored["recommended_formats"] if scored else []
            media_tags = scored["related_media_tags"] if scored else []
            readiness = scored["media_readiness_score"] if scored else 0.0
            explanation = scored["explanation"] if scored else "Тема выбрана ботом."

            fmt = topic_taxonomy.RECOMMENDED_FORMATS[
                index % len(topic_taxonomy.RECOMMENDED_FORMATS)
            ]
            if recommended_formats and fmt not in recommended_formats:
                fmt = recommended_formats[index % len(recommended_formats)]

            needs_media = readiness <= 0.0
            suggested_query: str | None = None
            if needs_media:
                tags_hint = ", ".join(media_tags) if media_tags else topic.cluster or topic.title
                suggested_query = f"Нужны медиа по тегам: {tags_hint} (папка 06_Нужно_переснять)"

            items.append(
                ContentPlanItem(
                    week_number=week_number,
                    slot_number=slot_number,
                    suggested_day=_SLOT_DAYS.get(slot_number, f"День {slot_number}"),
                    topic_title=topic.title,
                    cluster=topic.cluster or "",
                    recommended_format=fmt,
                    priority_score=topic.priority_score,
                    seo_keywords=list(topic.seo_keywords or []),
                    media_tags=list(media_tags),
                    explanation=explanation,
                    needs_media=needs_media,
                    suggested_media_query=suggested_query,
                )
            )

        return WeeklyContentPlan(
            project_id=project_id,
            project_slug=project_slug,
            weeks=request.weeks,
            posts_per_week=request.posts_per_week,
            items=items,
            warnings=warnings,
        )

    def _build_media_context(self, db: Session, project_id: int) -> dict[str, Any]:
        assets = media_asset_repository.list_media_assets_by_project(db, project_id)
        readiness_by_tag: dict[str, float] = {}
        approved_count = 0
        for asset in assets:
            tags = asset.tags or {}
            asset_tags: set[str] = set()
            for group in ("products", "technologies", "details", "categories", "use_cases"):
                for value in tags.get(group, []) or []:
                    asset_tags.add(value)
            rank = _STATUS_READINESS.get(asset.status, 0.0)
            if asset.status in ("approved", "approved_video"):
                approved_count += 1
            for tag in asset_tags:
                readiness_by_tag[tag] = max(readiness_by_tag.get(tag, 0.0), rank)
        return {
            "readiness_by_tag": readiness_by_tag,
            "total_assets": len(assets),
            "approved_count": approved_count,
        }

    @staticmethod
    def _media_readiness_score(related_tags: list[str], media_context: dict[str, Any]) -> float:
        readiness_by_tag: dict[str, float] = media_context.get("readiness_by_tag", {})
        if not related_tags:
            return 0.0
        return max((readiness_by_tag.get(tag, 0.0) for tag in related_tags), default=0.0)

    @staticmethod
    def _business_priority(
        candidate: dict[str, Any], business_priorities: dict[str, int] | None
    ) -> tuple[float, int]:
        default = int(candidate["default_business_priority"])
        if business_priorities:
            normalized = {
                topic_taxonomy.normalize_topic_key(key): value
                for key, value in business_priorities.items()
            }
            max_value = max(normalized.values()) if normalized else 0
            keys = [candidate["cluster"], *candidate["related_media_tags"]]
            matched = [
                normalized[topic_taxonomy.normalize_topic_key(key)]
                for key in keys
                if topic_taxonomy.normalize_topic_key(key) in normalized
            ]
            if matched and max_value > 0:
                value = max(matched)
                return min(value / max_value, 1.0), int(value)
        return min(default / 100.0, 1.0), default

    @staticmethod
    def _build_explanation(
        candidate: dict[str, Any],
        commercial_intent: float,
        search_demand: float,
        media_readiness: float,
        bp_score: float,
        business_priorities: dict[str, int] | None,
    ) -> str:
        parts: list[str] = []
        cluster = candidate["cluster"]
        if business_priorities and bp_score >= 0.99:
            parts.append(f"высокий бизнес-приоритет направления '{cluster}'")
        elif bp_score >= 0.7:
            parts.append(f"приоритетное направление '{cluster}'")
        if commercial_intent >= 0.8:
            parts.append("высокая коммерческая релевантность")
        if search_demand >= 0.7:
            parts.append("высокий поисковый спрос")
        related = ", ".join(candidate["related_media_tags"]) or cluster
        if media_readiness >= 1.0:
            parts.append(f"наличие approved-медиа по тегам: {related}")
        elif media_readiness > 0:
            parts.append("есть подходящие медиа (требуют проверки/досъёмки)")
        else:
            parts.append("медиа по теме пока нет (нужна досъёмка)")
        if not parts:
            parts.append("базовая релевантность направлению")
        return "Тема выбрана: " + "; ".join(parts) + "."
