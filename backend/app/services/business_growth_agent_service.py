"""BusinessGrowthAgentService — AI Business Growth Agent (v0.6.9).

Advisory-слой бизнес-аналитики: сводит Content + Campaigns + Leads + Revenue + Learning в
Growth Intelligence и превращает в Growth Recommendations. Botfleet оценивает рост
бизнеса и советует, но НИКОГДА не применяет сам: только Analyze → Recommend → Review →
Apply (с подтверждением).

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- НЕ меняет бизнес/CRM/бюджет автоматически, НЕ запускает рекламу и кампании;
- НЕ включает live и НЕ публикует; НЕ вызывает внешние действия;
- apply возможен ТОЛЬКО при status=accepted И подтверждении ``APPLY_GROWTH_ACTION``;
- apply меняет лишь business-профиль роста и/или создаёт draft-стратегию — не live/CRM;
- каждое изменение (analyzed/recommendation/accepted/rejected/applied) пишется в AuditLog.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import ai_learning_repository, project_repository
from app.repositories import business_growth_repository as repo
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.business_growth_profile import BusinessGrowthProfile
    from app.models.business_growth_recommendation import BusinessGrowthRecommendation
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

# Подтверждение, обязательное для применения рекомендации роста.
APPLY_CONFIRMATION = "APPLY_GROWTH_ACTION"

# Веса growth_score (в сумме 100).
_W_REVENUE = 40.0
_W_CONVERSION = 25.0
_W_CONTENT = 20.0
_W_LEARNING = 15.0
# Ориентир нормализации выручки в компонент 0..1 (эвристика).
_REVENUE_TARGET = 100000.0


class BusinessGrowthError(Exception):
    """Ошибка growth-агента (нет проекта/рекомендации/подтверждения) — API → 400/404."""


class BusinessGrowthAgentService:
    """Advisory growth-агент: analyze → recommend → review → apply."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Профиль / чтение                                                   #
    # ------------------------------------------------------------------ #

    def get_or_create_profile(self, db: Session, project_id: int) -> BusinessGrowthProfile:
        """Создать/получить профиль роста проекта."""
        self._require_project(db, project_id)
        return repo.get_or_create_profile(
            db, project_id, account_id=self._account_id(db, project_id)
        )

    def get_growth(self, db: Session, project_id: int) -> dict[str, Any]:
        """Текущее состояние роста (профиль + счётчик открытых рекомендаций)."""
        profile = self.get_or_create_profile(db, project_id)
        return repo.build_growth_summary(db, profile)

    def list_recommendations(
        self, db: Session, project_id: int, status: str | None = None
    ) -> list[dict[str, Any]]:
        """Список рекомендаций роста (по статусу)."""
        self._require_project(db, project_id)
        return [
            repo.public_recommendation_view(r)
            for r in repo.list_recommendations(db, project_id, status=status)
        ]

    # ------------------------------------------------------------------ #
    # Анализ бизнеса                                                     #
    # ------------------------------------------------------------------ #

    def analyze_business(
        self,
        db: Session,
        project_id: int,
        user_id: int | None = None,
        signals: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Собрать Growth Intelligence из всех слоёв и сохранить профиль роста."""
        self._require_project(db, project_id)
        profile = repo.get_or_create_profile(
            db, project_id, account_id=self._account_id(db, project_id)
        )
        signals = signals if signals is not None else self._gather_signals(db, project_id)
        score = self._calculate_growth_score(signals)
        strengths = self._strengths(signals)
        weaknesses = self._weaknesses(signals)
        opportunities = self.detect_growth_opportunities(db, project_id, signals=signals)
        risks = self._risks(signals)
        current_state = {
            "total_revenue": signals["total_revenue"],
            "leads": signals["leads"],
            "conversion_rate": signals["conversion"],
            "best_platform": signals["best_platform"],
            "learning_score": signals["learning_score"],
            "content_efficiency": round(signals["content_efficiency"] * 100, 1),
        }
        repo.update_profile(
            db,
            profile,
            status="active",
            growth_score=score,
            strengths=strengths,
            weaknesses=weaknesses,
            opportunities=[o["title"] for o in opportunities],
            risks=risks,
            current_state=current_state,
            last_analysis_at=datetime.now(UTC),
        )
        self._write_audit(
            db,
            audit_actions.ACTION_GROWTH_ANALYZED,
            project_id,
            user_id,
            {"growth_score": score, "opportunities": len(opportunities)},
        )
        return {
            "project_id": project_id,
            "growth_score": score,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "opportunities": opportunities,
            "risks": risks,
            "current_state": current_state,
        }

    # ------------------------------------------------------------------ #
    # Поиск возможностей роста                                           #
    # ------------------------------------------------------------------ #

    def detect_growth_opportunities(
        self, db: Session, project_id: int, signals: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Найти возможности роста по агрегированным сигналам."""
        self._require_project(db, project_id)
        s = signals if signals is not None else self._gather_signals(db, project_id)
        out: list[dict[str, Any]] = []

        # 1) Высокий трафик + мало лидов → проблема конверсии/CTA.
        reach = s["reach"]
        leads = s["leads"]
        if reach >= 3000 and (leads == 0 or leads / max(reach, 1) < 0.005):
            out.append(
                {
                    "type": "conversion",
                    "title": "Усилить конверсию: много просмотров, мало заявок",
                    "reason": "Высокий охват, но мало лидов — не хватает продающих CTA/офферов.",
                    "confidence": 75.0,
                    "signals": ["audience", "conversion"],
                }
            )
        # 2) Выручка концентрируется на одной теме → масштабировать её.
        top_content = s["top_content"]
        total_rev = s["total_revenue"]
        if top_content and total_rev > 0:
            top = top_content[0]
            share = float(top["revenue"]) / total_rev if total_rev else 0.0
            if share >= 0.5 and top.get("title"):
                out.append(
                    {
                        "type": "content",
                        "title": f"Масштабировать тему «{top['title']}»",
                        "reason": f"Тема даёт {round(share * 100)}% выручки — усилить её долю.",
                        "confidence": 85.0,
                        "signals": ["revenue", "content"],
                    }
                )
        # 3) Сильный канал с выручкой → увеличить активность.
        if s["best_platform"] and total_rev > 0:
            out.append(
                {
                    "type": "channel",
                    "title": f"Увеличить активность в канале: {s['best_platform']}",
                    "reason": "Этот канал приносит больше всего выручки.",
                    "confidence": 70.0,
                    "signals": ["platform", "revenue"],
                }
            )
        # 4) Успешная кампания → повторить/усилить.
        top_campaigns = s["top_campaigns"]
        if top_campaigns and float(top_campaigns[0].get("revenue", 0)) > 0:
            tc = top_campaigns[0]
            out.append(
                {
                    "type": "campaign",
                    "title": f"Повторить кампанию «{tc.get('name') or tc.get('campaign_id')}»",
                    "reason": f"Кампания эффективна (score {tc.get('campaign_revenue_score')}).",
                    "confidence": 65.0,
                    "signals": ["campaign", "revenue"],
                }
            )
        # 5) Слабые темы → пересмотреть контент.
        if s["weak_topics"]:
            out.append(
                {
                    "type": "content",
                    "title": "Пересмотреть слабые темы контента",
                    "reason": "Часть тем не приносит отклика/выручки — заменить или улучшить.",
                    "confidence": 55.0,
                    "signals": ["content", "efficiency"],
                }
            )
        return out

    # ------------------------------------------------------------------ #
    # Growth score                                                       #
    # ------------------------------------------------------------------ #

    def calculate_growth_score(self, db: Session, project_id: int) -> dict[str, Any]:
        """Оценка роста 0..100 (revenue 40 + conversion 25 + content 20 + learning 15)."""
        self._require_project(db, project_id)
        s = self._gather_signals(db, project_id)
        return {
            "project_id": project_id,
            "growth_score": self._calculate_growth_score(s),
            "components": self._score_components(s),
        }

    def _score_components(self, s: dict[str, Any]) -> dict[str, float]:
        revenue = round(min(1.0, s["total_revenue"] / _REVENUE_TARGET) * _W_REVENUE, 1)
        conversion = round(min(1.0, s["conversion"]) * _W_CONVERSION, 1)
        content = round(min(1.0, s["content_efficiency"]) * _W_CONTENT, 1)
        learning = round(min(1.0, s["learning_score"] / 100.0) * _W_LEARNING, 1)
        return {
            "revenue": revenue,
            "conversion": conversion,
            "content": content,
            "learning": learning,
        }

    def _calculate_growth_score(self, s: dict[str, Any]) -> float:
        return round(sum(self._score_components(s).values()), 1)

    # ------------------------------------------------------------------ #
    # Генерация рекомендаций                                             #
    # ------------------------------------------------------------------ #

    def generate_recommendations(
        self,
        db: Session,
        project_id: int,
        user_id: int | None = None,
        signals: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Создать рекомендации роста из возможностей (Recommendation → Review → Apply)."""
        self._require_project(db, project_id)
        if not self._resolve_settings().business_growth_enabled_effective:
            return []
        s = signals if signals is not None else self._gather_signals(db, project_id)
        account_id = self._account_id(db, project_id)
        opportunities = self.detect_growth_opportunities(db, project_id, signals=s)
        existing = {
            (r.recommendation_type, r.title) for r in repo.list_recommendations(db, project_id)
        }
        created: list[dict[str, Any]] = []
        for i, opp in enumerate(opportunities):
            key = (opp["type"], opp["title"])
            if key in existing:
                continue
            row = repo.create_recommendation(
                db,
                project_id=project_id,
                account_id=account_id,
                recommendation_type=opp["type"],
                title=opp["title"],
                description=opp["reason"],
                priority=90 - i * 5,
                confidence_score=opp["confidence"],
                reasoning=[opp["reason"]],
                source_signals=opp.get("signals", []),
                expected_impact={"growth": "рост"},
                apply_payload={"growth_targets": {opp["type"]: opp["title"]}},
            )
            existing.add(key)
            created.append(repo.public_recommendation_view(row))
        self._write_audit(
            db,
            audit_actions.ACTION_GROWTH_RECOMMENDATION_CREATED,
            project_id,
            user_id,
            {"created": len(created)},
        )
        return created

    def analyze_and_recommend(
        self, db: Session, project_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Полный проход: анализ + рекомендации (один сбор сигналов)."""
        self._require_project(db, project_id)
        signals = self._gather_signals(db, project_id)
        analysis = self.analyze_business(db, project_id, user_id=user_id, signals=signals)
        recommendations = self.generate_recommendations(
            db, project_id, user_id=user_id, signals=signals
        )
        return {"analysis": analysis, "recommendations": recommendations}

    # ------------------------------------------------------------------ #
    # Объяснение                                                         #
    # ------------------------------------------------------------------ #

    def explain_growth(self, db: Session, project_id: int) -> dict[str, Any]:
        """Объяснение для клиента: почему AI рекомендует это."""
        profile = self.get_or_create_profile(db, project_id)
        reasons: list[str] = []
        reasons.append(f"Growth Score: {round(float(profile.growth_score or 0.0), 1)}/100")
        if profile.strengths:
            reasons.append("Что работает: " + ", ".join(str(x) for x in profile.strengths[:3]))
        if profile.opportunities:
            reasons.append("Где рост: " + ", ".join(str(x) for x in profile.opportunities[:3]))
        if profile.risks:
            reasons.append("Риски: " + ", ".join(str(x) for x in profile.risks[:2]))
        state = profile.current_state or {}
        if state.get("total_revenue") is not None:
            reasons.append(
                f"Выручка: {state.get('total_revenue')}, конверсия: "
                f"{round(float(state.get('conversion_rate', 0) or 0) * 100, 1)}%"
            )
        if len(reasons) <= 1:
            reasons.append("Запустите анализ (analyze), чтобы собрать картину роста бизнеса.")
        return {
            "project_id": project_id,
            "status": profile.status,
            "growth_score": round(float(profile.growth_score or 0.0), 1),
            "reasons": reasons,
        }

    # ------------------------------------------------------------------ #
    # Review / Apply                                                     #
    # ------------------------------------------------------------------ #

    def accept_recommendation(
        self, db: Session, project_id: int, recommendation_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Одобрить рекомендацию роста (status=accepted)."""
        rec = self._require_recommendation(db, project_id, recommendation_id)
        if rec.status == "applied":
            raise BusinessGrowthError("Рекомендация уже применена")
        repo.accept(db, rec)
        self._write_audit(
            db, audit_actions.ACTION_GROWTH_ACCEPTED, project_id, user_id, {"rec_id": rec.id}
        )
        return repo.public_recommendation_view(rec)

    def reject_recommendation(
        self, db: Session, project_id: int, recommendation_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Отклонить рекомендацию роста (status=rejected)."""
        rec = self._require_recommendation(db, project_id, recommendation_id)
        if rec.status == "applied":
            raise BusinessGrowthError("Рекомендация уже применена")
        repo.reject(db, rec)
        self._write_audit(
            db, audit_actions.ACTION_GROWTH_REJECTED, project_id, user_id, {"rec_id": rec.id}
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
        """Применить рекомендацию. ТОЛЬКО status=accepted И confirmation=APPLY_GROWTH_ACTION.

        Меняет ЛИШЬ business-профиль роста (growth_targets/business_goal) и/или создаёт
        draft-стратегию. НЕ включает live, НЕ публикует, НЕ меняет CRM/бюджет.
        """
        rec = self._require_recommendation(db, project_id, recommendation_id)
        if rec.status != "accepted":
            raise BusinessGrowthError("Сначала одобрите рекомендацию (accept)")
        if confirmation != APPLY_CONFIRMATION:
            raise BusinessGrowthError("Требуется подтверждение APPLY_GROWTH_ACTION")

        payload = dict(rec.apply_payload or {})
        applied: dict[str, Any] = {"growth_profile": False, "draft_strategy": False}
        profile = repo.get_or_create_profile(
            db, project_id, account_id=self._account_id(db, project_id)
        )
        if payload.get("growth_targets"):
            merged = {**(profile.growth_targets or {}), **payload["growth_targets"]}
            repo.update_profile(db, profile, growth_targets=merged)
            applied["growth_profile"] = True
        if payload.get("business_goal"):
            merged_goal = {**(profile.business_goal or {}), **payload["business_goal"]}
            repo.update_profile(db, profile, business_goal=merged_goal)
            applied["growth_profile"] = True
        if payload.get("draft_strategy"):
            applied["draft_strategy"] = self._build_draft_strategy(db, project_id)

        repo.apply(db, rec)
        self._write_audit(
            db,
            audit_actions.ACTION_GROWTH_APPLIED,
            project_id,
            user_id,
            {"rec_id": rec.id, "applied": applied},
        )
        return {
            "recommendation": repo.public_recommendation_view(rec),
            "applied": applied,
            "live_enabled": False,  # инвариант: apply НЕ включает live/публикацию/CRM
            "note": "Обновлён business-профиль/черновик стратегии. Live/CRM/бюджет не менялись.",
        }

    # ------------------------------------------------------------------ #
    # Внутреннее: сбор сигналов                                          #
    # ------------------------------------------------------------------ #

    def _gather_signals(self, db: Session, project_id: int) -> dict[str, Any]:
        """Собрать сигналы из Sales / Content / Learning / Campaigns / Analytics."""
        sales_analysis = self._sales_analysis(db, project_id)
        revenue_summary = self._revenue_summary(db, project_id)
        content = self._content_snapshot(db, project_id)
        learning = ai_learning_repository.get_profile(db, project_id)
        analytics = self._analytics_summary(db, project_id)

        leads = int(revenue_summary.get("leads", 0) or 0)
        won = int(revenue_summary.get("won_deals", 0) or 0)
        conversion = min(1.0, won / leads) if leads else 0.0
        learning_score = float(getattr(learning, "learning_score", 0.0) or 0.0) if learning else 0.0
        content_eff = 0.0
        if learning is not None:
            avg = (learning.content_rules or {}).get("avg_performance")
            if isinstance(avg, (int, float)):
                content_eff = min(1.0, float(avg) / 100.0)
        return {
            "total_revenue": float(sales_analysis.get("total_revenue", 0.0) or 0.0),
            "leads": leads,
            "won_deals": won,
            "conversion": round(conversion, 3),
            "best_platform": sales_analysis.get("best_platform", ""),
            "best_cta": sales_analysis.get("best_cta", []),
            "top_content": sales_analysis.get("top_content", []),
            "top_campaigns": sales_analysis.get("top_campaigns", []),
            "best_topics": content.get("best_topics", []),
            "weak_topics": content.get("weak_topics", []),
            "best_formats": content.get("best_formats", []),
            "learning_score": learning_score,
            "content_efficiency": content_eff,
            "reach": int(analytics.get("total_reach", 0) or 0),
            "impressions": int(analytics.get("total_impressions", 0) or 0),
        }

    def _sales_analysis(self, db: Session, project_id: int) -> dict[str, Any]:
        try:
            from app.services.ai_sales_intelligence_service import AISalesIntelligenceService

            return AISalesIntelligenceService(
                settings=self._resolve_settings()
            ).analyze_content_revenue(db, project_id)
        except Exception:  # noqa: BLE001 — вспомогательный слой не критичен
            return {}

    @staticmethod
    def _revenue_summary(db: Session, project_id: int) -> dict[str, Any]:
        try:
            from app.repositories import ai_sales_intelligence_repository as sales_repo

            return sales_repo.build_revenue_summary(db, project_id)
        except Exception:  # noqa: BLE001
            return {}

    def _content_snapshot(self, db: Session, project_id: int) -> dict[str, Any]:
        try:
            from app.services.content_strategist_service import ContentStrategistService

            return ContentStrategistService(
                settings=self._resolve_settings()
            ).build_strategy_snapshot(db, project_id)
        except Exception:  # noqa: BLE001
            return {}

    def _analytics_summary(self, db: Session, project_id: int) -> dict[str, Any]:
        try:
            from app.services.analytics_service import AnalyticsService

            report = AnalyticsService().get_project_summary(db, project_id)
            return {
                "total_reach": getattr(report, "total_reach", 0),
                "total_impressions": getattr(report, "total_impressions", 0),
            }
        except Exception:  # noqa: BLE001
            return {}

    def _build_draft_strategy(self, db: Session, project_id: int) -> bool:
        """Обновить draft-стратегию проекта (ContentStrategyProfile). Без live/публикаций."""
        try:
            from app.services.content_strategist_service import ContentStrategistService

            ContentStrategistService(settings=self._resolve_settings()).build_strategy_snapshot(
                db, project_id
            )
            return True
        except Exception as exc:  # noqa: BLE001 — сбой черновика не критичен
            logger.warning("growth draft strategy failed: %s", type(exc).__name__)
            return False

    # ------------------------------------------------------------------ #
    # Внутреннее: деривация текста                                       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _strengths(s: dict[str, Any]) -> list[str]:
        out: list[str] = []
        if s["total_revenue"] > 0:
            out.append("Контент приносит выручку")
        if s["top_content"]:
            top = s["top_content"][0]
            if top.get("title"):
                out.append(f"Сильная тема: {top['title']}")
        if s["best_platform"]:
            out.append(f"Сильный канал: {s['best_platform']}")
        if s["best_cta"]:
            out.append("Есть работающий CTA")
        if s["learning_score"] >= 50:
            out.append("Стабильное обучение бренда")
        if not out:
            out.append("Данных пока мало — соберём после публикаций и продаж")
        return out

    @staticmethod
    def _weaknesses(s: dict[str, Any]) -> list[str]:
        out: list[str] = []
        if s["total_revenue"] <= 0:
            out.append("Пока нет выручки из контента")
        if s["leads"] and s["conversion"] < 0.2:
            out.append("Низкая конверсия лид→сделка")
        if s["weak_topics"]:
            out.append("Есть слабые темы: " + ", ".join(str(t) for t in s["weak_topics"][:2]))
        if s["learning_score"] < 30:
            out.append("Мало данных обучения — выводы предварительны")
        return out

    @staticmethod
    def _risks(s: dict[str, Any]) -> list[str]:
        out: list[str] = []
        platforms_with_rev = 1 if s["best_platform"] else 0
        if platforms_with_rev == 1 and s["total_revenue"] > 0:
            out.append("Зависимость от одного канала — стоит диверсифицировать")
        if s["leads"] == 0:
            out.append("Нет данных по лидам — фиксируйте заявки по постам")
        if s["learning_score"] < 20:
            out.append("Недостаточно данных для устойчивых выводов")
        return out

    # ------------------------------------------------------------------ #
    # Инфраструктура                                                     #
    # ------------------------------------------------------------------ #

    def _require_project(self, db: Session, project_id: int) -> Any:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise BusinessGrowthError(f"Проект id={project_id} не найден")
        return project

    def _require_recommendation(
        self, db: Session, project_id: int, recommendation_id: int
    ) -> BusinessGrowthRecommendation:
        rec = repo.get_recommendation_by_id(db, recommendation_id)
        if rec is None or rec.project_id != project_id:
            raise BusinessGrowthError("Рекомендация не найдена")
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
            entity_type="business_growth_profile",
            metadata=metadata,
        )


def get_business_growth_agent_service() -> BusinessGrowthAgentService:
    """DI-фабрика AI Business Growth Agent."""
    return BusinessGrowthAgentService()
