"""AICampaignManagerService — автономный AI Campaign Manager (v0.6.7).

Botfleet переходит от «создавать хорошие посты» к «управлять кампаниями»: цель +
продукт + аудитория + период → стратегия (этапы воронки/темы/форматы/CTA/KPI) →
рекомендации → approve → ЧЕРНОВИК календаря. Слой ПЛАНИРОВАНИЯ поверх Content Strategy
(v0.6.6), AI Learning (v0.6.5), аналитики, SEO и трендов.

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- кампания НЕ публикует, НЕ включает live, НЕ вызывает внешние рекламные API;
- НЕ меняет активный календарь — apply создаёт лишь ЧЕРНОВИК (draft);
- apply возможен ТОЛЬКО при status=approved И подтверждении ``APPLY_CAMPAIGN``;
- каждое изменение (created/planned/recommendation/approved/applied) пишется в AuditLog;
- строго per-project; секретов/токенов не хранит.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import ai_campaign_repository as repo
from app.repositories import project_repository
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.ai_campaign import AICampaign
    from app.models.ai_campaign_recommendation import AICampaignRecommendation
    from app.services.audit_log_service import AuditLogService
    from app.services.content_strategist_service import ContentStrategistService

logger = get_logger(__name__)

# Подтверждение, обязательное для применения кампании.
APPLY_CONFIRMATION = "APPLY_CAMPAIGN"

# Цель кампании → этапы воронки (какие ступени подсвечиваем).
_GOAL_STAGES: dict[str, tuple[str, ...]] = {
    "awareness": ("awareness", "interest"),
    "sales": ("awareness", "interest", "trust", "conversion"),
    "launch": ("awareness", "interest", "conversion"),
    "engagement": ("interest", "trust", "retention"),
    "education": ("awareness", "interest", "trust"),
    "recruitment": ("awareness", "trust", "conversion"),
}
_FULL_FUNNEL: tuple[str, ...] = ("awareness", "interest", "trust", "conversion", "retention")

# Этап → человекочитаемое имя.
_STAGE_LABELS: dict[str, str] = {
    "awareness": "Знакомство",
    "interest": "Интерес",
    "trust": "Доверие",
    "conversion": "Конверсия",
    "retention": "Удержание",
}
# Этап → CTA-стратегия.
_STAGE_CTA: dict[str, dict[str, str]] = {
    "awareness": {"cta": "Подпишитесь, чтобы не пропустить", "intent": "follow"},
    "interest": {"cta": "Узнайте больше о продукте", "intent": "learn"},
    "trust": {"cta": "Смотрите отзывы и кейсы", "intent": "proof"},
    "conversion": {"cta": "Оставьте заявку / Заказать", "intent": "convert"},
    "retention": {"cta": "Оставайтесь с нами — впереди больше пользы", "intent": "retain"},
}
# Цель → KPI (первичный/вторичный).
_GOAL_KPI: dict[str, dict[str, str]] = {
    "sales": {"primary": "conversions", "secondary": "ctr"},
    "awareness": {"primary": "reach", "secondary": "impressions"},
    "launch": {"primary": "reach", "secondary": "engagement"},
    "engagement": {"primary": "engagement_rate", "secondary": "saves"},
    "education": {"primary": "saves", "secondary": "engagement"},
    "recruitment": {"primary": "leads", "secondary": "reach"},
}
_GOAL_LABELS: dict[str, str] = {
    "sales": "Продажи",
    "awareness": "Узнаваемость",
    "launch": "Запуск продукта",
    "engagement": "Вовлечение",
    "education": "Обучение аудитории",
    "recruitment": "Найм",
}
# Цель кампании → цель календаря (AUTOPILOT_CALENDAR_GOALS: sales/leads/reach/trust/
# expertise/mixed) — чтобы черновик отражал именно ЭТУ кампанию, а не проектный дефолт.
_CAMPAIGN_TO_CALENDAR_GOAL: dict[str, str] = {
    "sales": "sales",
    "awareness": "reach",
    "launch": "reach",
    "engagement": "trust",
    "education": "expertise",
    "recruitment": "trust",
}


class AICampaignError(Exception):
    """Ошибка кампании (нет проекта/кампании/подтверждения) — API → 400/404."""


class AICampaignManagerService:
    """Автономный кампейн-менеджер: campaign → plan → review → approve → draft."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
        strategist: ContentStrategistService | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings
        self._strategist_svc = strategist

    # ------------------------------------------------------------------ #
    # Создание / чтение                                                  #
    # ------------------------------------------------------------------ #

    def create_campaign(
        self,
        db: Session,
        project_id: int,
        *,
        name: str,
        goal: str,
        product_context: dict[str, Any] | None = None,
        audience_context: dict[str, Any] | None = None,
        business_context: dict[str, Any] | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        description: str | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Создать кампанию (status=draft)."""
        from app.models.ai_campaign import CAMPAIGN_GOALS

        self._require_project(db, project_id)
        clean_name = (name or "").strip()
        if not clean_name:
            raise AICampaignError("Укажите название кампании")
        if goal not in CAMPAIGN_GOALS:
            raise AICampaignError("Неизвестная цель кампании")
        campaign = repo.create_campaign(
            db,
            project_id=project_id,
            account_id=self._account_id(db, project_id),
            name=clean_name,
            goal=goal,
            description=description,
            product_context=product_context,
            audience_context=audience_context,
            business_context=business_context,
            start_date=start_date,
            end_date=end_date,
            created_by_user_id=user_id,
        )
        self._write_audit(
            db,
            audit_actions.ACTION_CAMPAIGN_CREATED,
            campaign,
            user_id,
            {"goal": goal, "name": clean_name},
        )
        return repo.public_campaign_view(campaign)

    def get_campaign(self, db: Session, campaign_id: int) -> dict[str, Any]:
        """Кампания + этапы + счётчик открытых рекомендаций."""
        campaign = self._require_campaign(db, campaign_id)
        return {
            **repo.public_campaign_view(campaign),
            "stages": [repo.public_stage_view(s) for s in repo.list_stages(db, campaign_id)],
            "recommendations_open": len(
                repo.list_recommendations(db, campaign_id, status="generated")
            ),
        }

    def list_campaigns(self, db: Session, project_id: int) -> list[dict[str, Any]]:
        """Список кампаний проекта."""
        self._require_project(db, project_id)
        return [repo.public_campaign_view(c) for c in repo.list_campaigns(db, project_id)]

    def get_strategy(self, db: Session, campaign_id: int) -> dict[str, Any]:
        """Сохранённая стратегия кампании (read-only, без пересчёта)."""
        campaign = self._require_campaign(db, campaign_id)
        return {
            "campaign_id": campaign.id,
            "status": campaign.status,
            "strategy": dict(campaign.strategy_snapshot or {}),
            "kpi_targets": dict(campaign.kpi_targets or {}),
        }

    def list_recommendations(
        self, db: Session, campaign_id: int, status: str | None = None
    ) -> list[dict[str, Any]]:
        """Рекомендации кампании (по статусу)."""
        self._require_campaign(db, campaign_id)
        return [
            repo.public_recommendation_view(r)
            for r in repo.list_recommendations(db, campaign_id, status=status)
        ]

    # ------------------------------------------------------------------ #
    # Стратегия / план / рекомендации                                    #
    # ------------------------------------------------------------------ #

    def build_campaign_strategy(
        self, db: Session, campaign_id: int, snapshot: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Собрать стратегию кампании из Content Strategy + Learning + аналитики + SEO/трендов."""
        campaign = self._require_campaign(db, campaign_id)
        snapshot = snapshot or self._snapshot(db, campaign.project_id)
        strategy = self._derive_strategy(campaign, snapshot)
        repo.update_campaign(
            db,
            campaign,
            status="planning" if campaign.status == "draft" else campaign.status,
            strategy_snapshot=strategy,
            kpi_targets=strategy["kpi"],
        )
        return strategy

    def generate_campaign_plan(
        self,
        db: Session,
        campaign_id: int,
        snapshot: dict[str, Any] | None = None,
        strategy: dict[str, Any] | None = None,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Создать этапы кампании (воронка). Пере-генерация заменяет прежние этапы."""
        campaign = self._require_campaign(db, campaign_id)
        if campaign.status in ("active", "completed"):
            raise AICampaignError("Нельзя перепланировать применённую/завершённую кампанию")
        snapshot = snapshot or self._snapshot(db, campaign.project_id)
        strategy = strategy or self.build_campaign_strategy(db, campaign_id, snapshot)
        repo.delete_stages(db, campaign_id)  # пере-генерация плана этой кампании
        stage_types = _GOAL_STAGES.get(campaign.goal, _FULL_FUNNEL)
        topics = list(snapshot.get("best_topics") or []) or ["Экспертный контент"]
        formats = list(snapshot.get("best_formats") or []) or ["expert"]
        pillars = [
            p.get("name") if isinstance(p, dict) else str(p)
            for p in (snapshot.get("content_pillars") or [])
        ]
        duration = self._stage_duration(campaign, len(stage_types))
        created: list[dict[str, Any]] = []
        for i, stage_type in enumerate(stage_types):
            stage_topics = [topics[(i + j) % len(topics)] for j in range(2)]
            stage = repo.create_stage(
                db,
                campaign_id=campaign_id,
                stage_type=stage_type,
                order_number=i + 1,
                title=_STAGE_LABELS.get(stage_type, stage_type),
                description=self._stage_description(stage_type, campaign.goal),
                goal=campaign.goal,
                content_pillars=pillars[:3],
                recommended_formats=formats[:3],
                recommended_topics=stage_topics,
                cta_strategy=_STAGE_CTA.get(stage_type, {}),
                duration_days=duration,
            )
            created.append(repo.public_stage_view(stage))
        # План (пере)создан → всегда возвращаем в review и снимаем прежнее одобрение,
        # чтобы изменённый план требовал повторного approve перед apply.
        repo.update_campaign(db, campaign, status="review", approved_at=None)
        self._write_audit(
            db, audit_actions.ACTION_CAMPAIGN_PLANNED, campaign, user_id, {"stages": len(created)}
        )
        return created

    def generate_recommendations(
        self,
        db: Session,
        campaign_id: int,
        snapshot: dict[str, Any] | None = None,
        strategy: dict[str, Any] | None = None,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Создать рекомендации кампании (topic/post/schedule/media/cta)."""
        campaign = self._require_campaign(db, campaign_id)
        if not self._resolve_settings().ai_campaign_enabled_effective:
            return []
        snapshot = snapshot or self._snapshot(db, campaign.project_id)
        strategy = strategy or self.build_campaign_strategy(db, campaign_id, snapshot)
        existing = {
            (r.recommendation_type, r.title) for r in repo.list_recommendations(db, campaign_id)
        }
        created: list[dict[str, Any]] = []

        def _add(rec_type: str, title: str, **kw: Any) -> None:
            if (rec_type, title) in existing:
                return
            row = repo.create_recommendation(
                db, campaign_id=campaign_id, recommendation_type=rec_type, title=title, **kw
            )
            existing.add((rec_type, title))
            created.append(repo.public_recommendation_view(row))

        for topic in (snapshot.get("best_topics") or [])[:3]:
            _add(
                "topic",
                f"Тема кампании: «{topic}»",
                priority=90,
                confidence_score=80.0,
                reasoning=["Сильная тема по обучению/аналитике", "Совпадает с целью кампании"],
                expected_result={"engagement": "рост", "reach": "рост"},
            )
        for fmt in (snapshot.get("best_formats") or [])[:2]:
            _add(
                "media",
                f"Формат: {fmt}",
                priority=70,
                confidence_score=70.0,
                reasoning=["Формат с лучшим откликом у клиента (AI Learning)"],
                expected_result={"engagement": "рост"},
            )
        _add(
            "schedule",
            f"Частота публикаций: {strategy['posting_frequency']}",
            priority=60,
            confidence_score=65.0,
            reasoning=["Оптимальная частота по стратегии проекта"],
            expected_result={"consistency": "рост"},
        )
        _add(
            "cta",
            f"CTA под цель «{_GOAL_LABELS.get(campaign.goal, campaign.goal)}»",
            priority=55,
            confidence_score=60.0,
            reasoning=["CTA выстроен по воронке этапов кампании"],
            expected_result={"conversion": "рост"},
        )
        _add(
            "post",
            "Запланировать посты по этапам воронки",
            priority=50,
            confidence_score=60.0,
            reasoning=["Каждому этапу — свои темы/форматы/CTA"],
            expected_result={"structure": "рост"},
        )
        self._write_audit(
            db,
            audit_actions.ACTION_CAMPAIGN_RECOMMENDATION_GENERATED,
            campaign,
            user_id,
            {"created": len(created)},
        )
        return created

    def plan_campaign(
        self, db: Session, campaign_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Полный проход: стратегия → этапы → рекомендации (один снапшот)."""
        campaign = self._require_campaign(db, campaign_id)
        snapshot = self._snapshot(db, campaign.project_id)
        strategy = self.build_campaign_strategy(db, campaign_id, snapshot)
        stages = self.generate_campaign_plan(
            db, campaign_id, snapshot=snapshot, strategy=strategy, user_id=user_id
        )
        recs = self.generate_recommendations(
            db, campaign_id, snapshot=snapshot, strategy=strategy, user_id=user_id
        )
        return {"strategy": strategy, "stages": stages, "recommendations": recs}

    # ------------------------------------------------------------------ #
    # Объяснение                                                         #
    # ------------------------------------------------------------------ #

    def explain_campaign(self, db: Session, campaign_id: int) -> dict[str, Any]:
        """Объяснение для клиента: почему AI построил такую кампанию."""
        campaign = self._require_campaign(db, campaign_id)
        strategy = dict(campaign.strategy_snapshot or {})
        reasons: list[str] = []
        reasons.append(f"Цель кампании: {_GOAL_LABELS.get(campaign.goal, campaign.goal)}")
        if strategy.get("best_topics"):
            reasons.append(
                "Взяли сильные темы клиента (AI Learning + аналитика): "
                + ", ".join(str(t) for t in strategy["best_topics"][:3])
            )
        if strategy.get("content_mix"):
            reasons.append(
                "Форматы под предпочтения аудитории: "
                + ", ".join(str(f) for f in strategy["content_mix"])
            )
        if strategy.get("seo_keywords"):
            reasons.append("Учли SEO-спрос по ключевым запросам проекта")
        if strategy.get("trends"):
            reasons.append("Добавили трендовые направления")
        stages = repo.list_stages(db, campaign_id)
        if stages:
            reasons.append(
                "Построили воронку этапов: "
                + " → ".join(_STAGE_LABELS.get(s.stage_type, s.stage_type) for s in stages)
            )
        if len(reasons) <= 1:
            reasons.append("Запустите планирование (generate), чтобы собрать стратегию кампании.")
        return {
            "campaign_id": campaign.id,
            "goal": campaign.goal,
            "status": campaign.status,
            "reasons": reasons,
        }

    # ------------------------------------------------------------------ #
    # Review / Approve / Apply                                           #
    # ------------------------------------------------------------------ #

    def accept_recommendation(
        self, db: Session, campaign_id: int, recommendation_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Одобрить рекомендацию кампании (status=accepted)."""
        rec = self._require_recommendation(db, campaign_id, recommendation_id)
        if rec.status == "applied":
            raise AICampaignError("Рекомендация уже применена")
        repo.accept_recommendation(db, rec)
        campaign = self._require_campaign(db, campaign_id)
        self._write_audit(
            db,
            audit_actions.ACTION_CAMPAIGN_RECOMMENDATION_ACCEPTED,
            campaign,
            user_id,
            {"rec_id": rec.id},
        )
        return repo.public_recommendation_view(rec)

    def reject_recommendation(
        self, db: Session, campaign_id: int, recommendation_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Отклонить рекомендацию кампании (status=rejected)."""
        rec = self._require_recommendation(db, campaign_id, recommendation_id)
        if rec.status == "applied":
            raise AICampaignError("Рекомендация уже применена")
        repo.reject_recommendation(db, rec)
        campaign = self._require_campaign(db, campaign_id)
        self._write_audit(
            db,
            audit_actions.ACTION_CAMPAIGN_RECOMMENDATION_REJECTED,
            campaign,
            user_id,
            {"rec_id": rec.id},
        )
        return repo.public_recommendation_view(rec)

    def approve_campaign(
        self, db: Session, campaign_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Одобрить кампанию (status=approved) — обязательный шаг перед apply.

        Требует пройденного планирования (status=review, где созданы этапы воронки).
        """
        campaign = self._require_campaign(db, campaign_id)
        if campaign.status not in ("review", "approved"):
            raise AICampaignError("Сначала спланируйте кампанию (generate) — нужен этап review")
        repo.update_campaign(db, campaign, status="approved", approved_at=datetime.now(UTC))
        self._write_audit(
            db,
            audit_actions.ACTION_CAMPAIGN_APPROVED,
            campaign,
            user_id,
            {"campaign_id": campaign.id},
        )
        return repo.public_campaign_view(campaign)

    def apply_campaign(
        self,
        db: Session,
        campaign_id: int,
        confirmation: str = "",
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Применить кампанию → ЧЕРНОВИК календаря. Только approved + APPLY_CAMPAIGN.

        НЕ публикует, НЕ включает live, НЕ активирует календарь.
        """
        campaign = self._require_campaign(db, campaign_id)
        if campaign.status != "approved":
            raise AICampaignError("Сначала одобрите кампанию (approve)")
        if confirmation != APPLY_CONFIRMATION:
            raise AICampaignError("Требуется подтверждение APPLY_CAMPAIGN")

        draft_created = self._create_calendar_draft(db, campaign, user_id)
        repo.update_campaign(db, campaign, status="active", applied_at=datetime.now(UTC))
        self._write_audit(
            db,
            audit_actions.ACTION_CAMPAIGN_APPLIED,
            campaign,
            user_id,
            {"calendar_draft": draft_created},
        )
        return {
            "campaign": repo.public_campaign_view(campaign),
            "calendar_draft_created": draft_created,
            "live_enabled": False,  # инвариант: apply НЕ включает live и НЕ публикует
            "note": "Создан ЧЕРНОВИК календаря. Публикация и активный календарь не запускались.",
        }

    # ------------------------------------------------------------------ #
    # Календарь-превью (без записи)                                      #
    # ------------------------------------------------------------------ #

    def campaign_calendar_preview(self, db: Session, campaign_id: int) -> dict[str, Any]:
        """Предпросмотр будущего календаря кампании (week 1..4). Без записи."""
        campaign = self._require_campaign(db, campaign_id)
        stages = repo.list_stages(db, campaign_id)
        weeks: list[dict[str, Any]] = []
        preview: dict[str, Any] = {}
        try:
            from app.services.autopilot_calendar_assistant_service import (
                AutopilotCalendarAssistantService,
            )

            assistant = AutopilotCalendarAssistantService(settings=self._resolve_settings())
            preview = assistant.create_calendar_plan(
                db,
                campaign.project_id,
                self._calendar_payload(assistant, db, campaign),
                current_user_id=None,
                dry_run=True,  # гарантированно без записи
            )
        except Exception as exc:  # noqa: BLE001 — превью не критично
            logger.warning("campaign calendar preview failed: %s", type(exc).__name__)

        # Раскладываем этапы по неделям (по одному этапу на неделю, максимум 4).
        stage_views = [repo.public_stage_view(s) for s in stages] or []
        for i in range(4):
            stage = stage_views[i % len(stage_views)] if stage_views else None
            weeks.append(
                {
                    "week": i + 1,
                    "stage": (stage or {}).get("stage_type") if stage else None,
                    "theme": (stage or {}).get("title") if stage else None,
                    "topics": (stage or {}).get("recommended_topics", []) if stage else [],
                    "formats": (stage or {}).get("recommended_formats", []) if stage else [],
                }
            )
        return {
            "campaign_id": campaign.id,
            "weeks": weeks,
            "calendar_preview": preview,
            "writes": False,
        }

    # ------------------------------------------------------------------ #
    # Внутреннее: деривация стратегии                                    #
    # ------------------------------------------------------------------ #

    def _derive_strategy(self, campaign: AICampaign, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Чистая деривация стратегии кампании из снапшота проекта + контекста кампании."""
        best_topics = list(snapshot.get("best_topics") or [])
        best_formats = list(snapshot.get("best_formats") or [])
        product = str((campaign.product_context or {}).get("name") or "").strip()
        pillar = ""
        pillars = snapshot.get("content_pillars") or []
        if pillars:
            first = pillars[0]
            pillar = str(first.get("name") or "") if isinstance(first, dict) else str(first)
        theme_subject = product or pillar or (best_topics[0] if best_topics else "бренд")
        campaign_theme = f"{_GOAL_LABELS.get(campaign.goal, campaign.goal)}: {theme_subject}"
        stage_types = list(_GOAL_STAGES.get(campaign.goal, _FULL_FUNNEL))
        content_mix = self._content_mix(best_formats)
        kpi = {
            **_GOAL_KPI.get(campaign.goal, {"primary": "reach", "secondary": "engagement"}),
            "goal": campaign.goal,
        }
        return {
            "campaign_theme": campaign_theme,
            "stages": stage_types,
            "content_mix": content_mix,
            "best_topics": best_topics[:8],
            "weak_topics": list(snapshot.get("weak_topics") or [])[:5],
            "posting_frequency": str(snapshot.get("recommended_frequency") or "3_week"),
            "seo_keywords": (snapshot.get("seo") or {}).get("keywords", [])[:8],
            "trends": [t.get("topic") for t in (snapshot.get("trends") or [])][:5],
            "kpi": kpi,
        }

    @staticmethod
    def _content_mix(best_formats: list[Any]) -> dict[str, int]:
        """Распределение форматов по весам (проценты, сумма ~100)."""
        formats = [str(f) for f in best_formats[:3]] or ["expert"]
        weights = {1: [100], 2: [60, 40], 3: [50, 30, 20]}[len(formats)]
        return dict(zip(formats, weights, strict=True))

    @staticmethod
    def _stage_duration(campaign: AICampaign, stage_count: int) -> int:
        """Длительность этапа в днях (по периоду кампании или дефолт 7)."""
        if campaign.start_date and campaign.end_date and stage_count > 0:
            total = int((campaign.end_date - campaign.start_date).days)
            if total > 0:
                return max(1, total // stage_count)
        return 7

    @staticmethod
    def _stage_description(stage_type: str, goal: str) -> str:
        base = {
            "awareness": "Знакомим аудиторию с брендом и продуктом.",
            "interest": "Раскрываем ценность и детали продукта.",
            "trust": "Строим доверие: кейсы, отзывы, экспертиза.",
            "conversion": "Ведём к целевому действию (заявка/покупка).",
            "retention": "Удерживаем и возвращаем аудиторию.",
        }
        return base.get(stage_type, "Этап кампании.")

    @staticmethod
    def _calendar_payload(assistant: Any, db: Session, campaign: AICampaign) -> dict[str, Any]:
        """Payload календаря для ЭТОЙ кампании: preset из проекта + цель из цели кампании."""
        recommended = assistant.recommend_calendar(db, campaign.project_id)
        goal = _CAMPAIGN_TO_CALENDAR_GOAL.get(campaign.goal) or recommended.get("goal") or "mixed"
        return {"preset": recommended.get("recommended_preset"), "goal": goal}

    def _create_calendar_draft(
        self, db: Session, campaign: AICampaign, user_id: int | None
    ) -> bool:
        """Создать ЧЕРНОВИК календаря (status=draft) под цель кампании. Не активный, не live."""
        try:
            from app.services.autopilot_calendar_assistant_service import (
                AutopilotCalendarAssistantService,
            )

            assistant = AutopilotCalendarAssistantService(settings=self._resolve_settings())
            assistant.create_calendar_plan(
                db,
                campaign.project_id,
                self._calendar_payload(assistant, db, campaign),
                current_user_id=user_id,
                dry_run=False,  # dry_run=False → черновик (status=draft), НЕ публикация/актив
            )
            return True
        except Exception as exc:  # noqa: BLE001 — сбой черновика не должен ронять apply
            logger.warning("campaign calendar draft failed: %s", type(exc).__name__)
            return False

    # ------------------------------------------------------------------ #
    # Инфраструктура                                                     #
    # ------------------------------------------------------------------ #

    def _snapshot(self, db: Session, project_id: int) -> dict[str, Any]:
        """Снапшот стратегии проекта (reuse ContentStrategistService, v0.6.6)."""
        return self._strategist().build_strategy_snapshot(db, project_id)

    def _strategist(self) -> ContentStrategistService:
        if self._strategist_svc is None:
            from app.services.content_strategist_service import ContentStrategistService

            self._strategist_svc = ContentStrategistService(settings=self._resolve_settings())
        return self._strategist_svc

    def _require_project(self, db: Session, project_id: int) -> Any:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise AICampaignError(f"Проект id={project_id} не найден")
        return project

    def _require_campaign(self, db: Session, campaign_id: int) -> AICampaign:
        campaign = repo.get_campaign(db, campaign_id)
        if campaign is None:
            raise AICampaignError(f"Кампания id={campaign_id} не найдена")
        return campaign

    def _require_recommendation(
        self, db: Session, campaign_id: int, recommendation_id: int
    ) -> AICampaignRecommendation:
        rec = repo.get_recommendation(db, recommendation_id)
        if rec is None or rec.campaign_id != campaign_id:
            raise AICampaignError("Рекомендация не найдена")
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
        campaign: AICampaign,
        user_id: int | None,
        metadata: dict[str, Any],
    ) -> None:
        if self._audit_svc is None:
            from app.services.audit_log_service import AuditLogService

            self._audit_svc = AuditLogService(self._resolve_settings())
        self._audit_svc.record(
            db,
            action,
            account_id=campaign.account_id,
            user_id=user_id,
            project_id=campaign.project_id,
            entity_type="ai_campaign",
            entity_id=campaign.id,
            metadata=metadata,
        )


def get_ai_campaign_manager_service() -> AICampaignManagerService:
    """DI-фабрика AI Campaign Manager."""
    return AICampaignManagerService()
