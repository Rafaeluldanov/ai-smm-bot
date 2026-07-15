"""AISalesIntelligenceService — AI Sales & Lead Intelligence (v0.6.8).

Botfleet понимает не только просмотры/лайки, а бизнес-результат: какие публикации и
кампании создают лиды и выручку. Главный принцип: **Content → Lead → Revenue Attribution**.
Слой АНАЛИТИЧЕСКИЙ: собирает сигналы → считает атрибуцию → строит рекомендации.

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- НЕ отправляет сообщения клиентам, НЕ меняет CRM, НЕ продаёт автоматически;
- НЕ включает live и НЕ публикует; НЕ вызывает внешние рекламные/CRM API (CRM-адаптер mock);
- каждое изменение (analyzed/lead_created/attribution_created/reset) пишется в AuditLog;
- reset НЕ удаляет историю событий лидов; строго per-project; секретов не хранит.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.core.redaction import sanitize_metadata
from app.repositories import ai_learning_repository, post_repository, project_repository
from app.repositories import ai_sales_intelligence_repository as repo
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.sales_intelligence_profile import SalesIntelligenceProfile
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

_REVENUE_EVENTS: tuple[str, ...] = ("deal_won", "revenue_added")
_ATTRIBUTION_MODELS: tuple[str, ...] = ("first_touch", "last_touch", "multi_touch")


class AISalesIntelligenceError(Exception):
    """Ошибка sales-intelligence (нет проекта/данных) — API → 400/404."""


class AISalesIntelligenceService:
    """Аналитика продаж из контента: события → атрибуция → профиль → рекомендации."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Приём событий лидов                                                #
    # ------------------------------------------------------------------ #

    def record_lead_event(
        self,
        db: Session,
        project_id: int,
        *,
        event_type: str,
        source_type: str = "manual",
        status: str = "new",
        post_id: int | None = None,
        campaign_id: int | None = None,
        platform_key: str | None = None,
        value: float = 0.0,
        metadata: dict[str, Any] | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Записать событие лида/выручки (без секретов, без CRM/отправок)."""
        from app.models.ai_lead_event import (
            LEAD_SOURCE_TYPES,
            LEAD_STATUSES,
            REVENUE_SIGNAL_TYPES,
        )

        self._require_project(db, project_id)
        if event_type not in REVENUE_SIGNAL_TYPES:
            raise AISalesIntelligenceError("Неизвестный тип события лида")
        if source_type not in LEAD_SOURCE_TYPES:
            source_type = "manual"
        if status not in LEAD_STATUSES:
            status = "new"
        if float(value or 0.0) < 0:
            raise AISalesIntelligenceError("Отрицательная выручка не допускается")
        # Tenant isolation: пост/кампания должны принадлежать этому же проекту,
        # иначе анализ мог бы «подтянуть» чужие заголовки/названия/CTA.
        self._assert_belongs_to_project(db, project_id, post_id=post_id, campaign_id=campaign_id)
        row = repo.create_lead_event(
            db,
            project_id=project_id,
            account_id=self._account_id(db, project_id),
            event_type=event_type,
            source_type=source_type,
            status=status,
            post_id=post_id,
            campaign_id=campaign_id,
            platform_key=platform_key,
            value=float(value or 0.0),
            event_metadata=self._sanitize(metadata or {}),
        )
        self._write_audit(
            db,
            audit_actions.ACTION_SALES_INTELLIGENCE_LEAD_CREATED,
            project_id,
            user_id,
            {"event_type": event_type, "source_type": source_type, "value": float(value or 0.0)},
        )
        return repo.public_lead_event_view(row)

    # ------------------------------------------------------------------ #
    # Атрибуция выручки на контент                                       #
    # ------------------------------------------------------------------ #

    def calculate_attribution(
        self,
        db: Session,
        project_id: int,
        model: str | None = None,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Рассчитать атрибуцию выручки на контент по модели (first/last/multi touch).

        Группирует события в «путь лида» (по ``event_metadata.lead_ref``, иначе каждое
        событие — свой путь), берёт выручку пути и распределяет её по постам-касаниям:
        first_touch — первому, last_touch — последнему, multi_touch — поровну.
        """
        self._require_project(db, project_id)
        model = model or self._resolve_settings().sales_intelligence_default_attribution_model_safe
        if model not in _ATTRIBUTION_MODELS:
            raise AISalesIntelligenceError("Неизвестная модель атрибуции")
        account_id = self._account_id(db, project_id)
        repo.delete_attributions(db, project_id, attribution_model=model)  # идемпотентно
        journeys = self._journeys(db, project_id)
        created: list[dict[str, Any]] = []
        for evs in journeys:
            revenue = sum(float(e.value or 0.0) for e in evs if e.event_type in _REVENUE_EVENTS)
            if revenue <= 0:
                continue
            touches = self._touches(evs)
            if not touches:
                continue
            journey_campaign = self._journey_campaign(evs)
            last_event_id = evs[-1].id
            if model == "first_touch":
                targets = [(touches[0], revenue)]
            elif model == "last_touch":
                targets = [(touches[-1], revenue)]
            else:  # multi_touch — остаток отдаём последнему касанию (сумма = revenue)
                share = round(revenue / len(touches), 2)
                targets = [(t, share) for t in touches[:-1]]
                targets.append((touches[-1], round(revenue - share * (len(touches) - 1), 2)))
            conf = 75.0 if model == "multi_touch" and len(touches) > 1 else 65.0
            for (post_id, campaign_id), val in targets:
                campaign_id = campaign_id or journey_campaign  # не теряем привязку к кампании
                row = repo.create_attribution(
                    db,
                    project_id=project_id,
                    account_id=account_id,
                    attribution_model=model,
                    revenue_value=round(val, 2),
                    post_id=post_id,
                    campaign_id=campaign_id,
                    lead_event_id=last_event_id,
                    confidence_score=conf,
                    reasoning=[
                        f"{model}: выручка {round(val, 2)} отнесена на "
                        + (f"пост #{post_id}" if post_id else f"кампанию #{campaign_id}")
                    ],
                )
                created.append(repo.public_attribution_view(row))
        self._write_audit(
            db,
            audit_actions.ACTION_SALES_INTELLIGENCE_ATTRIBUTION_CREATED,
            project_id,
            user_id,
            {"model": model, "rows": len(created)},
        )
        return created

    # ------------------------------------------------------------------ #
    # Анализ выручки из контента                                         #
    # ------------------------------------------------------------------ #

    def analyze_content_revenue(self, db: Session, project_id: int) -> dict[str, Any]:
        """Что приносит деньги: топ-контент/кампании/CTA/площадка/источники выручки.

        Считается по last_touch (конвертирующее касание) прямо из событий — без записи.
        """
        self._require_project(db, project_id)
        post_revenue: dict[int, float] = defaultdict(float)
        campaign_revenue: dict[int, float] = defaultdict(float)
        platform_revenue: dict[str, float] = defaultdict(float)
        source_revenue: dict[str, float] = defaultdict(float)
        for evs in self._journeys(db, project_id):
            revenue = sum(float(e.value or 0.0) for e in evs if e.event_type in _REVENUE_EVENTS)
            if revenue <= 0:
                continue
            touches = self._touches(evs)
            journey_campaign = self._journey_campaign(evs)
            last = evs[-1]
            if touches:
                post_id, campaign_id = touches[-1]
                if post_id is not None:
                    post_revenue[post_id] += revenue
                camp = campaign_id or journey_campaign
                if camp is not None:
                    campaign_revenue[camp] += revenue
            if last.platform_key:
                platform_revenue[last.platform_key] += revenue
            source_revenue[last.source_type] += revenue

        top_content = [
            {
                "post_id": pid,
                "title": self._post_title(db, project_id, pid),
                "revenue": round(rev, 2),
            }
            for pid, rev in sorted(post_revenue.items(), key=lambda kv: kv[1], reverse=True)[:5]
        ]
        top_campaigns = [
            {
                "campaign_id": cid,
                "name": self._campaign_name(db, project_id, cid),
                "revenue": round(rev, 2),
                "campaign_revenue_score": self._campaign_score(rev, campaign_revenue),
            }
            for cid, rev in sorted(campaign_revenue.items(), key=lambda kv: kv[1], reverse=True)[:5]
        ]
        best_cta = self._best_cta(db, project_id, post_revenue)
        best_platform = (
            max(platform_revenue.items(), key=lambda kv: kv[1])[0] if platform_revenue else ""
        )
        return {
            "project_id": project_id,
            "top_content": top_content,
            "top_campaigns": top_campaigns,
            "best_cta": best_cta,
            "best_platform": best_platform,
            "revenue_sources": {k: round(v, 2) for k, v in source_revenue.items()},
            # Единый источник истины: source_revenue кредитуется один раз на путь лида
            # (= полная выручка проекта), без потери campaign-only/безкасательной выручки.
            "total_revenue": round(sum(source_revenue.values()), 2),
        }

    # ------------------------------------------------------------------ #
    # Профиль продаж                                                     #
    # ------------------------------------------------------------------ #

    def build_sales_profile(
        self, db: Session, project_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Пересчитать профиль продаж из событий/атрибуции + AI Learning."""
        self._require_project(db, project_id)
        profile = repo.get_or_create_profile(
            db, project_id, account_id=self._account_id(db, project_id)
        )
        if not self._resolve_settings().sales_intelligence_enabled_effective:
            return repo.public_profile_view(profile)
        analysis = self.analyze_content_revenue(db, project_id)
        # Пересчитываем атрибуцию по модели по умолчанию (создаёт строки атрибуции).
        self.calculate_attribution(db, project_id, user_id=user_id)
        summary = repo.build_revenue_summary(db, project_id)

        best_lead_topics = [c["title"] for c in analysis["top_content"] if c["title"]]
        best_campaigns = [c["name"] for c in analysis["top_campaigns"] if c["name"]]
        best_cta = list(analysis["best_cta"])
        best_platforms = [analysis["best_platform"]] if analysis["best_platform"] else []
        # AI Learning: что нравится аудитории + что продаёт → пересечение приоритетно.
        liked_and_selling = self._liked_and_selling(db, project_id, best_lead_topics)

        leads = summary["leads"]
        won = summary["won_deals"]
        conversion_patterns = {
            "leads": leads,
            "deals": summary["deals"],
            "won_deals": won,
            # Клампим в [0..1]: won может превышать число lead_created (лид без события).
            "conversion_rate": round(min(1.0, won / leads), 3) if leads else 0.0,
            "click_signals": self._conversion_signals(db, project_id),
        }
        revenue_insights = {
            "total_revenue": analysis["total_revenue"],
            "revenue_per_lead": round(analysis["total_revenue"] / leads, 2) if leads else 0.0,
            "revenue_sources": analysis["revenue_sources"],
            "campaign_scores": {
                str(c["campaign_id"]): c["campaign_revenue_score"]
                for c in analysis["top_campaigns"]
            },
            "topics_liked_and_selling": liked_and_selling,
        }
        repo.update_profile(
            db,
            profile,
            status="active",
            best_lead_topics=best_lead_topics[:8],
            best_campaigns=best_campaigns[:5],
            best_cta=best_cta[:5],
            best_platforms=best_platforms[:3],
            conversion_patterns=conversion_patterns,
            revenue_insights=revenue_insights,
            last_analysis_at=datetime.now(UTC),
        )
        self._write_audit(
            db,
            audit_actions.ACTION_SALES_INTELLIGENCE_ANALYZED,
            project_id,
            user_id,
            {"total_revenue": analysis["total_revenue"], "leads": leads},
        )
        return repo.public_profile_view(profile)

    # ------------------------------------------------------------------ #
    # Рекомендации / объяснение / чтение                                 #
    # ------------------------------------------------------------------ #

    def recommend_growth_actions(self, db: Session, project_id: int) -> dict[str, Any]:
        """Рекомендации роста выручки (только рекомендации, ничего не применяет)."""
        profile = self._get_or_create(db, project_id)
        actions: list[str] = []
        if profile.best_lead_topics:
            actions.append(
                "Больше публиковать темы, которые приносят заявки: "
                + ", ".join(str(t) for t in profile.best_lead_topics[:3])
            )
        if profile.best_cta:
            actions.append(
                "Чаще использовать работающий CTA: "
                + ", ".join(str(c) for c in profile.best_cta[:2])
            )
        if profile.best_platforms:
            actions.append("Масштабировать площадку с выручкой: " + str(profile.best_platforms[0]))
        if profile.best_campaigns:
            actions.append(
                "Повторить успешные кампании: "
                + ", ".join(str(c) for c in profile.best_campaigns[:2])
            )
        conv = (profile.conversion_patterns or {}).get("conversion_rate", 0.0)
        if (
            isinstance(conv, (int, float))
            and profile.conversion_patterns.get("leads")
            and conv < 0.2
        ):
            actions.append("Низкая конверсия лид→сделка — усилить офферы/CTA и работу с заявками.")
        if not actions:
            actions.append("Пока мало данных о продажах — фиксируйте лиды/выручку по постам.")
        return {"project_id": project_id, "actions": actions}

    def explain_revenue(self, db: Session, project_id: int) -> dict[str, Any]:
        """Объяснение для клиента: какие публикации принесли больше всего заявок/денег."""
        analysis = self.analyze_content_revenue(db, project_id)
        reasons: list[str] = []
        if analysis["top_content"]:
            top = analysis["top_content"][0]
            reasons.append(
                f"Больше всего денег принёс пост «{top['title'] or top['post_id']}» "
                f"(выручка {top['revenue']})"
            )
        if analysis["top_campaigns"]:
            tc = analysis["top_campaigns"][0]
            reasons.append(
                f"Сильнейшая кампания: «{tc['name'] or tc['campaign_id']}» ({tc['revenue']})"
            )
        if analysis["best_platform"]:
            reasons.append(f"Больше всего выручки с площадки: {analysis['best_platform']}")
        if analysis["best_cta"]:
            reasons.append("Рабочий призыв к действию: " + ", ".join(analysis["best_cta"][:2]))
        if not reasons:
            reasons.append(
                "Пока нет связанных с выручкой публикаций. Отмечайте лиды/сделки по постам."
            )
        return {
            "project_id": project_id,
            "reasons": reasons,
            "total_revenue": analysis["total_revenue"],
        }

    def get_intelligence(self, db: Session, project_id: int) -> dict[str, Any]:
        """Профиль продаж + сводка выручки + рекомендации (для клиента/UI)."""
        profile = self._get_or_create(db, project_id)
        return {
            **repo.public_profile_view(profile),
            "revenue_summary": repo.build_revenue_summary(db, project_id),
            "recommendations": self.recommend_growth_actions(db, project_id)["actions"],
        }

    def get_revenue(self, db: Session, project_id: int) -> dict[str, Any]:
        """Анализ выручки из контента + сводка (read-only)."""
        return {
            "analysis": self.analyze_content_revenue(db, project_id),
            "summary": repo.build_revenue_summary(db, project_id),
        }

    def reset(self, db: Session, project_id: int, user_id: int | None = None) -> dict[str, Any]:
        """Сбросить агрегаты профиля + производную атрибуцию (события лидов НЕ удаляем)."""
        profile = self._get_or_create(db, project_id)
        repo.delete_attributions(db, project_id)  # производные строки атрибуции
        repo.update_profile(
            db,
            profile,
            status="learning",
            best_lead_topics=[],
            best_campaigns=[],
            best_cta=[],
            best_platforms=[],
            conversion_patterns={},
            revenue_insights={},
            last_analysis_at=None,
        )
        self._write_audit(
            db,
            audit_actions.ACTION_SALES_INTELLIGENCE_RESET,
            project_id,
            user_id,
            {"lead_events_preserved": repo.count_lead_events(db, project_id)},
        )
        return repo.public_profile_view(profile)

    # ------------------------------------------------------------------ #
    # Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    def _journeys(self, db: Session, project_id: int) -> list[list[Any]]:
        """Сгруппировать события в пути лида (по lead_ref) и упорядочить по времени."""
        events = repo.list_lead_events(db, project_id, limit=5000)
        groups: dict[str, list[Any]] = defaultdict(list)
        for e in events:
            key = str((e.event_metadata or {}).get("lead_ref") or f"lead-{e.id}")
            groups[key].append(e)
        journeys: list[list[Any]] = []
        for evs in groups.values():
            evs.sort(
                key=lambda x: (x.id if x.created_at is None else x.created_at.timestamp(), x.id)
            )
            journeys.append(evs)
        return journeys

    @staticmethod
    def _touches(events: list[Any]) -> list[tuple[int | None, int | None]]:
        """Упорядоченные касания пути: distinct посты (иначе кампании)."""
        touches: list[tuple[int | None, int | None]] = []
        seen_posts: set[int] = set()
        for e in events:
            if e.post_id and e.post_id not in seen_posts:
                seen_posts.add(e.post_id)
                touches.append((e.post_id, e.campaign_id))
        if touches:
            return touches
        seen_camp: set[int] = set()
        for e in events:
            if e.campaign_id and e.campaign_id not in seen_camp:
                seen_camp.add(e.campaign_id)
                touches.append((None, e.campaign_id))
        return touches

    @staticmethod
    def _journey_campaign(events: list[Any]) -> int | None:
        """Кампания пути лида (из событий с выручкой) — чтобы не терять привязку кампании."""
        campaign_id: int | None = None
        for e in events:
            if e.event_type in _REVENUE_EVENTS and e.campaign_id:
                campaign_id = e.campaign_id
        if campaign_id is not None:
            return campaign_id
        for e in events:
            if e.campaign_id:
                return int(e.campaign_id)
        return None

    @staticmethod
    def _campaign_score(revenue: float, campaign_revenue: dict[int, float]) -> float:
        """campaign_revenue_score 0..100 относительно лучшей кампании."""
        best = max(campaign_revenue.values()) if campaign_revenue else 0.0
        return round(100.0 * revenue / best, 1) if best > 0 else 0.0

    def _best_cta(self, db: Session, project_id: int, post_revenue: dict[int, float]) -> list[str]:
        """CTA постов с наибольшей выручкой (из generation_notes), скоуп по проекту."""
        cta_revenue: dict[str, float] = defaultdict(float)
        for post_id, rev in post_revenue.items():
            post = post_repository.get_post_by_id(db, post_id)
            if post is None or post.project_id != project_id:
                continue
            notes = post.generation_notes or {}
            cta = str(notes.get("cta") or notes.get("category_cta") or "").strip()
            if cta:
                cta_revenue[cta] += rev
        return [c for c, _ in sorted(cta_revenue.items(), key=lambda kv: kv[1], reverse=True)[:5]]

    def _liked_and_selling(
        self, db: Session, project_id: int, revenue_topics: list[str]
    ) -> list[str]:
        """Темы, которые И нравятся аудитории (AI Learning), И приносят выручку."""
        learning = ai_learning_repository.get_profile(db, project_id)
        if learning is None:
            return []
        liked = {str(t).lower() for t in (learning.preferred_topics or [])}
        out: list[str] = []
        for topic in revenue_topics:
            tl = str(topic).lower()
            if any(tl in lk or lk in tl for lk in liked):
                out.append(topic)
        return out[:5]

    def _conversion_signals(self, db: Session, project_id: int) -> dict[str, Any]:
        """Сигналы конверсии из аналитики (клики) — грубая связь трафика и лидов."""
        try:
            from app.repositories import analytics_repository

            snaps = analytics_repository.list_snapshots_for_project(db, project_id)
            clicks = sum(int(getattr(s, "clicks", 0) or 0) for s in snaps)
            summary = repo.build_revenue_summary(db, project_id)
            leads = summary["leads"]
            return {
                "clicks": clicks,
                "leads": leads,
                "clicks_per_lead": round(clicks / leads, 2) if leads else 0.0,
            }
        except Exception:  # noqa: BLE001 — вспомогательный сигнал не критичен
            return {}

    @staticmethod
    def _assert_belongs_to_project(
        db: Session, project_id: int, *, post_id: int | None, campaign_id: int | None
    ) -> None:
        """Проверить, что пост/кампания принадлежат проекту (tenant isolation)."""
        if post_id is not None:
            post = post_repository.get_post_by_id(db, post_id)
            if post is None or post.project_id != project_id:
                raise AISalesIntelligenceError("Пост не найден в этом проекте")
        if campaign_id is not None:
            from app.repositories import ai_campaign_repository

            campaign = ai_campaign_repository.get_campaign(db, campaign_id)
            if campaign is None or campaign.project_id != project_id:
                raise AISalesIntelligenceError("Кампания не найдена в этом проекте")

    @staticmethod
    def _post_title(db: Session, project_id: int, post_id: int) -> str:
        # Скоуп по проекту (defense-in-depth): чужой заголовок не утечёт.
        post = post_repository.get_post_by_id(db, post_id)
        if post is None or post.project_id != project_id:
            return ""
        return str(post.title or "")

    @staticmethod
    def _campaign_name(db: Session, project_id: int, campaign_id: int) -> str:
        from app.repositories import ai_campaign_repository

        campaign = ai_campaign_repository.get_campaign(db, campaign_id)
        if campaign is None or campaign.project_id != project_id:
            return ""
        return str(campaign.name or "")

    def _get_or_create(self, db: Session, project_id: int) -> SalesIntelligenceProfile:
        self._require_project(db, project_id)
        return repo.get_or_create_profile(
            db, project_id, account_id=self._account_id(db, project_id)
        )

    def _require_project(self, db: Session, project_id: int) -> Any:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise AISalesIntelligenceError(f"Проект id={project_id} не найден")
        return project

    @staticmethod
    def _account_id(db: Session, project_id: int) -> int | None:
        project = project_repository.get_project_by_id(db, project_id)
        return project.account_id if project is not None else None

    @staticmethod
    def _sanitize(metadata: dict[str, Any]) -> dict[str, Any]:
        cleaned = sanitize_metadata(metadata)
        return cleaned if isinstance(cleaned, dict) else {}

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
            entity_type="sales_intelligence_profile",
            metadata=metadata,
        )


def get_ai_sales_intelligence_service() -> AISalesIntelligenceService:
    """DI-фабрика AI Sales & Lead Intelligence."""
    return AISalesIntelligenceService()
