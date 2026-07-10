"""Аналитика постов Botfleet: анализ контента, оценка метрик, отчёты и списание.

Показывает клиенту, как Botfleet анализирует опубликованные и запланированные посты
Telegram/VK, даже если часть метрик ещё не приходит по API. НИКАКИХ реальных вызовов
внешних API — метрики берутся из БД (internal), ручного ввода (manual), оценки по
тексту/структуре (estimated), сохранённых снапшотов (api/demo). Источник метрик всегда
указывается: оценка НЕ выдаётся за реальные данные.

Платный запуск отчёта (`run_analytics`) списывает units через ``BillingService``
(идемпотентно, не в минус). dry-run/preview и ручной ввод метрик — бесплатны.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.models.post import Post
from app.models.post_publication import PostPublication
from app.repositories import (
    analytics_repository,
    post_publication_repository,
    post_repository,
)
from app.services.audit_log_service import ACTION_ANALYTICS_RUN, AuditLogService
from app.services.billing_service import BillingService
from app.services.unit_economics_service import (
    ANALYTICS_DEPTHS,
    USAGE_POST_ANALYTICS,
    UnitEconomicsService,
)

# Источники аналитики (всегда указываются в ответе).
SOURCE_INTERNAL = "internal"
SOURCE_MANUAL = "manual"
SOURCE_ESTIMATED = "estimated"
SOURCE_API = "api"
SOURCE_DEMO = "demo"

# Ключевые слова для эвристик анализа текста.
_CTA_WORDS = (
    "закаж",
    "купить",
    "купи",
    "подпис",
    "напиши",
    "звони",
    "перейд",
    "оставь заявк",
    "в директ",
    "пиши",
    "заказать",
    "консультац",
    "подробнее",
    "ссылка в",
    "жми",
    "успей",
    "оформи",
)
_B2B_WORDS = (
    "опт",
    "b2b",
    "закупк",
    "поставщик",
    "тираж",
    "оптом",
    "договор",
    "юрлиц",
    " ип ",
    " ооо ",
    "прайс",
    "коммерческое предложение",
    "бизнес",
    "корпоратив",
    "мерч",
    "брендирован",
)
_URL_RE = re.compile(r"https?://|\bt\.me/|\bvk\.com/", re.IGNORECASE)
_DIGIT_RE = re.compile(r"\d")
_PRICE_RE = re.compile(r"\d[\d\s]*\s*(?:₽|руб|р\.|рублей)|цена|от\s+\d", re.IGNORECASE)

_IDEAL_MIN_LEN = 200
_IDEAL_MAX_LEN = 900


class PostAnalyticsError(Exception):
    """Ошибка аналитики постов (нет поста и т. п.) — API → 404/422."""


@dataclass(frozen=True)
class PostContentAnalysis:
    """Разбор контента поста: структура, признаки, оценки, рекомендации."""

    text_length: int
    has_link: bool
    has_cta: bool
    has_question: bool
    has_price_or_numbers: bool
    hashtags_count: int
    has_media: bool
    media_count: int
    paragraphs: int
    first_paragraph_length: int
    quality_score: int
    b2b_relevance_score: int
    recommendations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EstimatedMetrics:
    """Оценка потенциала поста (estimated), без реальных метрик."""

    engagement_score: int
    quality_score: int
    predicted_reach_level: str  # low | medium | high
    risk_flags: list[str] = field(default_factory=list)


class PostAnalyticsService:
    """Анализ постов, календарь, оценка стоимости и платный запуск отчёта."""

    def __init__(
        self,
        billing_service: BillingService | None = None,
        economics: UnitEconomicsService | None = None,
        audit_service: AuditLogService | None = None,
    ) -> None:
        self._billing = billing_service or BillingService()
        self._economics = economics or UnitEconomicsService()
        self._audit = audit_service or AuditLogService()

    # ------------------------------------------------------------------ #
    # 1. Анализ контента                                                 #
    # ------------------------------------------------------------------ #

    def _post_text(self, post: Post, platform: str | None = None) -> str:
        """Вернуть текст поста для платформы (или первый непустой)."""
        by_platform = {
            "telegram": post.telegram_text,
            "vk": post.vk_text,
            "instagram": post.instagram_text,
        }
        if platform and by_platform.get(platform):
            return by_platform[platform] or ""
        for value in (post.telegram_text, post.vk_text, post.instagram_text, post.title):
            if value:
                return value
        return ""

    def _media_count(self, post: Post) -> int:
        notes = post.generation_notes or {}
        ids = notes.get("media_asset_ids")
        if isinstance(ids, list) and ids:
            return len(ids)
        return 1 if post.media_asset_id else 0

    def analyze_post_content(
        self, post: Post, publication: PostPublication | None = None
    ) -> PostContentAnalysis:
        """Проанализировать контент поста (длина, ссылка, CTA, B2B, качество)."""
        platform = publication.platform if publication is not None else None
        text = self._post_text(post, platform)
        low = f" {text.lower()} "
        text_length = len(text)
        has_link = bool(_URL_RE.search(text))
        has_cta = any(word in low for word in _CTA_WORDS)
        has_question = "?" in text
        has_price = bool(_PRICE_RE.search(text)) or bool(_DIGIT_RE.search(text))
        hashtags = list(post.hashtags or [])
        hashtags_count = len(hashtags) or text.count("#")
        media_count = self._media_count(post)
        has_media = media_count > 0
        paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
        first_len = len(paragraphs[0]) if paragraphs else text_length

        # B2B-релевантность 0..100 по числу попаданий ключевых слов.
        b2b_hits = sum(1 for word in _B2B_WORDS if word in low)
        b2b_score = min(100, b2b_hits * 25)

        # Композитный quality_score 0..100.
        quality = 0
        quality += (
            25
            if _IDEAL_MIN_LEN <= text_length <= _IDEAL_MAX_LEN
            else (10 if text_length >= 60 else 0)
        )
        quality += 20 if has_media else 0
        quality += 20 if has_cta else 0
        quality += 15 if has_link else 0
        quality += 10 if 1 <= hashtags_count <= 8 else 0
        quality += 10 if len(paragraphs) >= 2 else 0
        quality = min(100, quality)

        recommendations = self._recommendations(
            text_length=text_length,
            has_cta=has_cta,
            has_link=has_link,
            has_question=has_question,
            has_price=has_price,
            has_media=has_media,
            media_count=media_count,
            first_len=first_len,
            b2b_score=b2b_score,
        )
        return PostContentAnalysis(
            text_length=text_length,
            has_link=has_link,
            has_cta=has_cta,
            has_question=has_question,
            has_price_or_numbers=has_price,
            hashtags_count=hashtags_count,
            has_media=has_media,
            media_count=media_count,
            paragraphs=len(paragraphs),
            first_paragraph_length=first_len,
            quality_score=quality,
            b2b_relevance_score=b2b_score,
            recommendations=recommendations,
        )

    @staticmethod
    def _recommendations(
        *,
        text_length: int,
        has_cta: bool,
        has_link: bool,
        has_question: bool,
        has_price: bool,
        has_media: bool,
        media_count: int,
        first_len: int,
        b2b_score: int,
    ) -> list[str]:
        recs: list[str] = []
        if first_len > 220:
            recs.append("усилить первый абзац (сделать короче и цепляюще)")
        if not has_cta:
            recs.append("добавить CTA")
        if not has_price:
            recs.append("добавить конкретный оффер")
        if text_length > _IDEAL_MAX_LEN:
            recs.append("сократить текст")
        if not has_price:
            recs.append("добавить цифры/тираж/срок")
        if not has_link:
            recs.append("добавить ссылку")
        if not has_question:
            recs.append("добавить вопрос в конце")
        if media_count == 1:
            recs.append("лучше использовать media-group")
        if not has_media:
            recs.append("пост без медиа может получить меньше вовлечения")
        if b2b_score < 25:
            recs.append("для B2B добавить кейс или выгоду для закупщика")
        return recs

    # ------------------------------------------------------------------ #
    # 2. Оценка метрик (estimated)                                        #
    # ------------------------------------------------------------------ #

    def estimate_post_metrics(
        self, post: Post, publication: PostPublication | None = None
    ) -> EstimatedMetrics:
        """Дать estimated-оценку потенциала поста (без реальных метрик)."""
        content = self.analyze_post_content(post, publication)
        engagement = content.quality_score
        engagement += 10 if content.has_question else 0
        engagement += 10 if content.media_count >= 2 else 0
        engagement = min(100, engagement)

        if content.quality_score >= 70 and content.has_media:
            level = "high"
        elif content.quality_score >= 40:
            level = "medium"
        else:
            level = "low"

        flags: list[str] = []
        if not content.has_media:
            flags.append("no_media")
        if content.text_length > _IDEAL_MAX_LEN:
            flags.append("too_long")
        if content.text_length < 60:
            flags.append("too_short")
        if not content.has_cta:
            flags.append("no_cta")
        if not content.has_link:
            flags.append("no_link")
        if content.b2b_relevance_score < 25:
            flags.append("low_b2b_value")
        return EstimatedMetrics(
            engagement_score=engagement,
            quality_score=content.quality_score,
            predicted_reach_level=level,
            risk_flags=flags,
        )

    # ------------------------------------------------------------------ #
    # 3. Карточка анализа поста                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _snapshot_source(raw_source: str) -> str:
        if raw_source == SOURCE_MANUAL:
            return SOURCE_MANUAL
        if raw_source.endswith("_api"):
            return SOURCE_API
        return SOURCE_DEMO

    def _metrics_from_snapshot(self, snapshot: Any) -> dict[str, Any]:
        reach = snapshot.reach or 0
        impressions = snapshot.impressions or 0
        engagements = (
            (snapshot.likes or 0)
            + (snapshot.comments or 0)
            + (snapshot.shares or 0)
            + (snapshot.saves or 0)
        )
        er = round(engagements / max(reach, 1), 4)
        ctr = round((snapshot.clicks or 0) / max(impressions, 1), 4)
        return {
            "views": snapshot.views or 0,
            "reach": reach,
            "impressions": impressions,
            "likes": snapshot.likes or 0,
            "comments": snapshot.comments or 0,
            "shares": snapshot.shares or 0,
            "saves": snapshot.saves or 0,
            "clicks": snapshot.clicks or 0,
            "followers_delta": (snapshot.raw_metrics or {}).get("followers_delta", 0),
            "er": er,
            "ctr": ctr,
            "source": self._snapshot_source(snapshot.source),
        }

    def build_post_analytics_card(
        self, db: Session, post_id: int, depth: str = "light"
    ) -> dict[str, Any]:
        """Собрать карточку анализа поста нужной глубины (light|standard|deep)."""
        depth_norm = (depth or "light").strip().lower()
        if depth_norm not in ANALYTICS_DEPTHS:
            raise ValueError(f"Неизвестная глубина: {depth!r}")
        post = post_repository.get_post_by_id(db, post_id)
        if post is None:
            raise PostAnalyticsError(f"Пост #{post_id} не найден")
        publications = post_publication_repository.list_publications(db, post_id=post_id)
        primary_pub = publications[0] if publications else None
        content = self.analyze_post_content(post, primary_pub)

        snapshot = analytics_repository.get_latest_snapshot_for_post_platform(
            db, post_id, primary_pub.platform if primary_pub else "telegram"
        )
        if snapshot is not None:
            metrics = self._metrics_from_snapshot(snapshot)
        else:
            # Реальных метрик нет — показываем оценку и честно помечаем источник.
            metrics = {
                "views": 0,
                "reach": 0,
                "impressions": 0,
                "likes": 0,
                "comments": 0,
                "shares": 0,
                "saves": 0,
                "clicks": 0,
                "followers_delta": 0,
                "er": 0.0,
                "ctr": 0.0,
                "source": SOURCE_ESTIMATED,
            }
        card: dict[str, Any] = {
            "post_id": post.id,
            "title": post.title,
            "status": post.status,
            "depth": depth_norm,
            "cost_units": self._economics.analytics_depth_price(depth_norm),
            "media_count": content.media_count,
            "metrics_source": metrics["source"],
            "metrics": metrics,
            "content": asdict(content),
            "publications": [
                {
                    "platform": p.platform,
                    "status": p.status,
                    "external_url": p.external_url,
                }
                for p in publications
            ],
        }
        if depth_norm in ("standard", "deep"):
            card["estimated"] = asdict(self.estimate_post_metrics(post, primary_pub))
        if depth_norm == "deep":
            card["recommendations"] = content.recommendations
            card["text"] = self._post_text(post, primary_pub.platform if primary_pub else None)
            card["next_post_hint"] = (
                "Повторить формат с сильным первым абзац+CTA и media-group; "
                "для B2B — добавить кейс/выгоду закупщику."
            )
        return card

    # ------------------------------------------------------------------ #
    # 4. Список постов и календарь                                        #
    # ------------------------------------------------------------------ #

    def list_project_posts_for_analytics(
        self,
        db: Session,
        project_id: int,
        platform: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Список постов проекта для аналитики (с фильтрами платформы/статуса)."""
        posts = post_repository.list_posts(db, project_id=project_id, limit=limit)
        rows: list[dict[str, Any]] = []
        for post in posts:
            if status is not None and post.status != status:
                continue
            pubs = post_publication_repository.list_publications(db, post_id=post.id)
            platforms = [p.platform for p in pubs]
            # Нет публикации на выбранной платформе (но пост где-то опубликован) — пропуск.
            if platform and platform != "all" and platforms and platform not in platforms:
                continue
            content = self.analyze_post_content(post, pubs[0] if pubs else None)
            estimated = self.estimate_post_metrics(post, pubs[0] if pubs else None)
            snapshot = analytics_repository.get_latest_snapshot_for_post_platform(
                db, post.id, platforms[0] if platforms else "telegram"
            )
            source = self._snapshot_source(snapshot.source) if snapshot else SOURCE_ESTIMATED
            rows.append(
                {
                    "post_id": post.id,
                    "title": post.title or f"#{post.id}",
                    "status": post.status,
                    "platforms": platforms,
                    "media_count": content.media_count,
                    "analytics_source": source,
                    "quality_score": content.quality_score,
                    "engagement_score": estimated.engagement_score,
                    "scheduled_at": post.scheduled_at.isoformat() if post.scheduled_at else None,
                    "published_at": post.published_at.isoformat() if post.published_at else None,
                }
            )
        return rows

    def build_calendar(
        self, db: Session, project_id: int, month: str | None = None, platform: str | None = None
    ) -> dict[str, Any]:
        """Календарь дней с постами: счётчики статусов и посты по дням.

        ``month`` — строка ``YYYY-MM`` (по ней фильтруются даты) или None (все посты).
        Дата берётся из published_at или scheduled_at.
        """
        posts = post_repository.list_posts(db, project_id=project_id, limit=500)
        days: dict[str, dict[str, Any]] = {}
        for post in posts:
            pubs = post_publication_repository.list_publications(db, post_id=post.id)
            platforms = [p.platform for p in pubs]
            if platform and platform != "all" and platform not in platforms and platforms:
                continue
            when = post.published_at or post.scheduled_at
            date_str = when.date().isoformat() if when else "—"
            if month and date_str != "—" and not date_str.startswith(month):
                continue
            day = days.setdefault(
                date_str,
                {
                    "date": date_str,
                    "scheduled_count": 0,
                    "published_count": 0,
                    "failed_count": 0,
                    "needs_review_count": 0,
                    "posts": [],
                },
            )
            if post.status == "published":
                day["published_count"] += 1
            elif post.status == "scheduled":
                day["scheduled_count"] += 1
            elif post.status == "rejected":
                day["failed_count"] += 1
            elif post.status == "needs_review":
                day["needs_review_count"] += 1
            day["posts"].append(
                {
                    "post_id": post.id,
                    "title": post.title or f"#{post.id}",
                    "status": post.status,
                    "platforms": platforms,
                }
            )
        return {
            "project_id": project_id,
            "month": month,
            "platform": platform or "all",
            "days": [days[k] for k in sorted(days)],
        }

    # ------------------------------------------------------------------ #
    # 5. Стоимость и запуск отчёта (платно/бесплатно)                     #
    # ------------------------------------------------------------------ #

    def preview_analytics_cost(
        self, db: Session, account_id: int, depth: str, post_count: int = 1
    ) -> dict[str, Any]:
        """Оценить стоимость отчёта (units) и доступность по балансу. Бесплатно."""
        units = self._economics.estimate_analytics_units(depth, post_count)
        balance = self._billing.get_balance(db, account_id).balance_units
        return {
            "depth": (depth or "").strip().lower(),
            "post_count": max(1, int(post_count or 1)),
            "estimated_units": units,
            "balance_units": balance,
            "affordable": balance >= units,
            "live_calls": False,
        }

    def run_analytics_dry(
        self,
        db: Session,
        account_id: int,
        project_id: int,
        depth: str,
        platform: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Dry-run отчёта: показать результат и estimated units БЕЗ списания."""
        posts = self.list_project_posts_for_analytics(db, project_id, platform, status)
        cost = self.preview_analytics_cost(db, account_id, depth, len(posts) or 1)
        return {
            "dry_run": True,
            "charged_units": 0,
            "estimated_units": cost["estimated_units"],
            "affordable": cost["affordable"],
            "post_count": len(posts),
            "posts": posts[:50],
            "live_calls": False,
        }

    def run_analytics(
        self,
        db: Session,
        account_id: int,
        project_id: int,
        depth: str,
        platform: str | None = None,
        status: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Платный запуск отчёта: проверить баланс, списать units, вернуть отчёт.

        Списание — через ``BillingService.reserve_or_debit`` (идемпотентно, не в
        минус). При недостатке баланса бросается ``InsufficientBalanceError`` и отчёт
        НЕ строится. Внешние API не вызываются.
        """
        depth_norm = (depth or "light").strip().lower()
        if depth_norm not in ANALYTICS_DEPTHS:
            raise ValueError(f"Неизвестная глубина: {depth!r}")
        posts = self.list_project_posts_for_analytics(db, project_id, platform, status)
        post_count = len(posts) or 1
        units = self._economics.estimate_analytics_units(depth_norm, post_count)
        # Списание ДО построения отчёта через единый платный путь (идемпотентно, не в
        # минус, уважает paid_actions_enforced). Недостаток баланса прервёт действие.
        self._billing.debit_for_action(
            db,
            account_id,
            units=units,
            usage_type=USAGE_POST_ANALYTICS,
            project_id=project_id,
            idempotency_key=idempotency_key,
            metadata={"depth": depth_norm, "post_count": post_count},
        )
        cards = [
            self.build_post_analytics_card(db, row["post_id"], depth_norm) for row in posts[:50]
        ]
        self._audit.record(
            db,
            ACTION_ANALYTICS_RUN,
            account_id=account_id,
            project_id=project_id,
            entity_type="analytics_report",
            metadata={"depth": depth_norm, "post_count": post_count, "charged_units": units},
        )
        return {
            "dry_run": False,
            "charged_units": units,
            "depth": depth_norm,
            "post_count": post_count,
            "report": cards,
            "live_calls": False,
        }


def get_post_analytics_service() -> PostAnalyticsService:
    """DI-фабрика сервиса аналитики постов (офлайн)."""
    return PostAnalyticsService()
