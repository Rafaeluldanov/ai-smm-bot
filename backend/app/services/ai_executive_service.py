"""AIExecutiveService — Autonomous Business OS / AI Executive Layer (v0.7.0).

Верхний уровень управления. Сводит всё, что знает Botfleet (Growth Agent, Sales
Intelligence, Content Strategy, Campaign Manager, Learning, Analytics), в исполнительное
состояние бизнеса, строит план по бизнес-цели и приоритизированные бизнес-действия.

Архитектура: Business Goal → Executive Analysis → Growth Priorities → Business Actions →
(Marketing/Sales Actions) → Learning Feedback. Это advisory + planning слой.

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- НЕ меняет бизнес/CRM/бюджет автоматически, НЕ запускает рекламу, НЕ публикует;
- НЕ включает live и НЕ совершает внешних действий;
- apply возможен ТОЛЬКО при status=accepted И подтверждении ``APPLY_BUSINESS_ACTION``;
- apply меняет лишь draft-стратегию и/или создаёт draft-кампанию — не live/CRM/деньги;
- каждое изменение (analyzed/plan_created/action_created/accepted/rejected/applied) — в AuditLog.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import business_os_repository as repo
from app.repositories import project_repository
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.business_action import BusinessAction
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

# Подтверждение, обязательное для применения бизнес-действия.
APPLY_CONFIRMATION = "APPLY_BUSINESS_ACTION"

# Максимальная длина title (совпадает с BusinessAction.title String(255)) — для дедупа.
_TITLE_MAX = 255

# Вес типа возможности при оценке impact (0..1).
_TYPE_IMPACT: dict[str, float] = {
    "revenue": 1.0,
    "conversion": 1.0,
    "sales": 0.9,
    "content": 0.8,
    "growth": 0.8,
    "channel": 0.7,
    "campaign": 0.7,
    "efficiency": 0.6,
}
# Возможность → тип действия/приоритета.
_OPP_TO_ACTION: dict[str, str] = {
    "conversion": "conversion",
    "content": "content",
    "channel": "sales",
    "campaign": "campaign",
    "revenue": "revenue",
}


class AIExecutiveError(Exception):
    """Ошибка Executive Layer (нет проекта/плана/действия/подтверждения) — API → 400/404."""


class AIExecutiveService:
    """AI-директор бизнеса: analyze → plan → prioritize → review → apply."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Цели                                                               #
    # ------------------------------------------------------------------ #

    def create_objective(
        self,
        db: Session,
        project_id: int,
        *,
        type: str,
        title: str,
        description: str | None = None,
        target_value: float = 0.0,
        current_value: float = 0.0,
        unit: str | None = None,
        deadline: datetime | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Создать бизнес-цель (status=draft)."""
        from app.models.business_objective import BUSINESS_OBJECTIVE_TYPES

        self._require_project(db, project_id)
        if type not in BUSINESS_OBJECTIVE_TYPES:
            raise AIExecutiveError("Неизвестный тип бизнес-цели")
        clean_title = (title or "").strip()
        if not clean_title:
            raise AIExecutiveError("Укажите название цели")
        objective = repo.create_objective(
            db,
            project_id=project_id,
            account_id=self._account_id(db, project_id),
            type=type,
            title=clean_title,
            description=description,
            target_value=target_value,
            current_value=current_value,
            unit=unit,
            deadline=deadline,
        )
        return repo.public_objective_view(objective)

    def list_objectives(self, db: Session, project_id: int) -> list[dict[str, Any]]:
        """Список бизнес-целей проекта."""
        self._require_project(db, project_id)
        return [repo.public_objective_view(o) for o in repo.list_objectives(db, project_id)]

    # ------------------------------------------------------------------ #
    # Анализ состояния бизнеса                                           #
    # ------------------------------------------------------------------ #

    def analyze_business_state(
        self, db: Session, project_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Собрать исполнительное состояние бизнеса из всех слоёв."""
        self._require_project(db, project_id)
        growth = self._growth_analysis(db, project_id, user_id)
        state = growth.get("current_state", {})
        growth_score = float(growth.get("growth_score", 0.0) or 0.0)
        total_revenue = float(state.get("total_revenue", 0.0) or 0.0)
        conversion = float(state.get("conversion_rate", 0.0) or 0.0)
        revenue_health = min(100.0, total_revenue / 1000.0)
        business_health = round(0.6 * growth_score + 0.4 * revenue_health, 1)
        return {
            "project_id": project_id,
            "business_health": business_health,
            "growth_score": growth_score,
            "revenue_state": {
                "total_revenue": total_revenue,
                "conversion_rate": conversion,
                "best_platform": state.get("best_platform", ""),
            },
            "content_state": {
                "content_efficiency": state.get("content_efficiency", 0.0),
                "weak_areas": growth.get("weaknesses", []),
            },
            "sales_state": {
                "leads": state.get("leads", 0),
                "conversion_rate": conversion,
                "revenue": total_revenue,
            },
            "risks": growth.get("risks", []),
            "opportunities": growth.get("opportunities", []),
            "strengths": growth.get("strengths", []),
        }

    # ------------------------------------------------------------------ #
    # Исполнительный план                                               #
    # ------------------------------------------------------------------ #

    def create_executive_plan(
        self,
        db: Session,
        project_id: int,
        objective_id: int | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Построить исполнительный план: резюме + приоритеты + действия."""
        self._require_project(db, project_id)
        if objective_id is not None:
            objective = repo.get_objective(db, objective_id)
            if objective is None or objective.project_id != project_id:
                raise AIExecutiveError("Цель не найдена в этом проекте")
        state = self.analyze_business_state(db, project_id, user_id=user_id)
        opportunities = list(state.get("opportunities") or [])
        summary = self._executive_summary(state)
        confidence = self._plan_confidence(state, opportunities)
        expected_outcomes = self._expected_outcomes(state)

        plan = repo.create_plan(
            db,
            project_id=project_id,
            account_id=self._account_id(db, project_id),
            objective_id=objective_id,
            executive_summary=summary,
            current_state={
                "business_health": state["business_health"],
                "growth_score": state["growth_score"],
                "revenue_state": state["revenue_state"],
                "content_state": state["content_state"],
                "sales_state": state["sales_state"],
            },
            risks=list(state.get("risks") or []),
            opportunities=[
                o.get("title") if isinstance(o, dict) else str(o) for o in opportunities
            ],
            expected_outcomes=expected_outcomes,
            confidence_score=confidence,
        )
        # Создаём новые действия из возможностей (dedup по (action_type, title)),
        # затем привязываем ВСЕ открытые действия проекта к новому плану — иначе повторный
        # analyze с теми же сигналами дал бы пустой план (все возможности задедуплены).
        self._generate_actions(db, project_id, plan.id, opportunities, user_id)
        open_actions = repo.reassign_open_actions_to_plan(db, project_id, plan.id)
        plan.priority_actions = [a.title for a in open_actions[:3]]  # уже по убыванию приоритета
        db.commit()

        self._write_audit(
            db,
            audit_actions.ACTION_BUSINESS_OS_PLAN_CREATED,
            project_id,
            user_id,
            {"plan_id": plan.id, "actions": len(open_actions)},
        )
        return {
            "plan": repo.public_plan_view(plan),
            "actions": [repo.public_action_view(a) for a in open_actions],
        }

    def get_plan(self, db: Session, project_id: int) -> dict[str, Any]:
        """Последний исполнительный план проекта (+ действия)."""
        self._require_project(db, project_id)
        plan = repo.get_latest_plan(db, project_id)
        if plan is None:
            return {"project_id": project_id, "has_plan": False, "plan": None, "actions": []}
        return {
            "project_id": project_id,
            "has_plan": True,
            "plan": repo.public_plan_view(plan),
            "actions": [
                repo.public_action_view(a)
                for a in repo.list_actions(db, project_id, plan_id=plan.id)
            ],
        }

    def get_business_summary(self, db: Session, project_id: int) -> dict[str, Any]:
        """Сводка бизнеса (для UI-состояния)."""
        self._require_project(db, project_id)
        return repo.build_business_summary(db, project_id)

    def list_actions(
        self, db: Session, project_id: int, status: str | None = None
    ) -> list[dict[str, Any]]:
        """Список бизнес-действий проекта (по статусу)."""
        self._require_project(db, project_id)
        return [
            repo.public_action_view(a) for a in repo.list_actions(db, project_id, status=status)
        ]

    # ------------------------------------------------------------------ #
    # Приоритизация                                                      #
    # ------------------------------------------------------------------ #

    def prioritize_actions(self, db: Session, project_id: int) -> list[dict[str, Any]]:
        """Действия проекта, отсортированные по приоритету (read-only)."""
        self._require_project(db, project_id)
        return [repo.public_action_view(a) for a in repo.list_actions(db, project_id)]

    @staticmethod
    def _priority_score(opp: dict[str, Any]) -> float:
        """priority = impact × confidence × urgency → 0..100."""
        confidence = float(opp.get("confidence", 50.0)) / 100.0
        type_weight = _TYPE_IMPACT.get(str(opp.get("type", "")), 0.6)
        impact = 0.5 * confidence + 0.5 * type_weight
        urgency = 0.7  # без дедлайна цели — умеренная срочность
        return round(max(0.0, min(100.0, impact * confidence * urgency * 100.0)), 1)

    # ------------------------------------------------------------------ #
    # Генерация действий                                                 #
    # ------------------------------------------------------------------ #

    def generate_actions(
        self, db: Session, project_id: int, user_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Сгенерировать бизнес-действия под последний план (или новый анализ)."""
        self._require_project(db, project_id)
        plan = repo.get_latest_plan(db, project_id)
        state = self.analyze_business_state(db, project_id, user_id=user_id)
        opportunities = list(state.get("opportunities") or [])
        plan_id = plan.id if plan is not None else None
        return self._generate_actions(db, project_id, plan_id, opportunities, user_id)

    def _generate_actions(
        self,
        db: Session,
        project_id: int,
        plan_id: int | None,
        opportunities: list[dict[str, Any]],
        user_id: int | None,
    ) -> list[dict[str, Any]]:
        if not self._resolve_settings().business_os_enabled_effective:
            return []
        account_id = self._account_id(db, project_id)
        # Ключ дедупа сравнивается с уже сохранёнными title (обрезаны до 255 в create_action),
        # поэтому кандидата тоже нормализуем через _TITLE_MAX — иначе длинные заголовки
        # (>255) обходили бы дедуп и плодили дубликаты при каждом analyze.
        existing = {(a.action_type, a.title) for a in repo.list_actions(db, project_id, limit=1000)}
        created: list[dict[str, Any]] = []
        for opp in opportunities:
            opp_type = str(opp.get("type", "content"))
            action_type = _OPP_TO_ACTION.get(opp_type, "content")
            title = str(opp.get("title", "")).strip()[:_TITLE_MAX]
            if not title or (action_type, title) in existing:
                continue
            priority = self._priority_score(opp)
            row = repo.create_action(
                db,
                project_id=project_id,
                account_id=account_id,
                plan_id=plan_id,
                action_type=action_type,
                title=title,
                priority=priority,
                description=str(opp.get("reason", "")),
                reasoning=[str(opp.get("reason", ""))],
                expected_impact={"business": "рост"},
                source_modules=self._source_modules(opp),
                apply_payload=self._apply_payload(action_type, title),
            )
            existing.add((action_type, title))
            created.append(repo.public_action_view(row))
        self._write_audit(
            db,
            audit_actions.ACTION_BUSINESS_OS_ACTION_CREATED,
            project_id,
            user_id,
            {"created": len(created)},
        )
        return created

    @staticmethod
    def _source_modules(opp: dict[str, Any]) -> list[str]:
        mods = {"growth_agent"}
        signals = {str(s) for s in (opp.get("signals") or [])}
        if signals & {"revenue", "conversion"}:
            mods.add("sales_intelligence")
        if signals & {"content", "efficiency"}:
            mods.add("content_strategy")
        if "campaign" in signals:
            mods.add("campaign_manager")
        return sorted(mods)

    @staticmethod
    def _apply_payload(action_type: str, title: str) -> dict[str, Any]:
        if action_type == "campaign":
            return {"draft_campaign": {"goal": "awareness", "name": title[:120]}}
        return {"draft_strategy": True}

    # ------------------------------------------------------------------ #
    # Объяснение                                                         #
    # ------------------------------------------------------------------ #

    def explain_plan(self, db: Session, project_id: int) -> dict[str, Any]:
        """Объяснение для владельца: почему AI выбрал именно эти действия."""
        plan = repo.get_latest_plan(db, project_id)
        if plan is None:
            self._require_project(db, project_id)
            return {
                "project_id": project_id,
                "reasons": ["Запустите анализ (analyze), чтобы AI собрал исполнительный план."],
            }
        reasons: list[str] = []
        if plan.executive_summary:
            reasons.append(plan.executive_summary)
        state = plan.current_state or {}
        rs = state.get("revenue_state", {})
        if rs:
            reasons.append(
                f"Данные продаж: выручка {rs.get('total_revenue', 0)}, конверсия "
                f"{round(float(rs.get('conversion_rate', 0) or 0) * 100, 1)}%"
            )
        if state.get("growth_score") is not None:
            reasons.append(f"Growth Score: {state.get('growth_score')}/100 (обучение + аналитика)")
        if plan.priority_actions:
            reasons.append("Приоритеты: " + ", ".join(str(a) for a in plan.priority_actions[:3]))
        if plan.risks:
            reasons.append("Учтены риски: " + ", ".join(str(r) for r in plan.risks[:2]))
        return {"project_id": project_id, "reasons": reasons}

    # ------------------------------------------------------------------ #
    # Review / Apply                                                     #
    # ------------------------------------------------------------------ #

    def accept_action(
        self, db: Session, action_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Одобрить бизнес-действие (status=accepted)."""
        action = self._require_action(db, action_id)
        if action.status == "applied":
            raise AIExecutiveError("Действие уже применено")
        repo.accept_action(db, action)
        self._write_audit(
            db,
            audit_actions.ACTION_BUSINESS_OS_ACCEPTED,
            action.project_id,
            user_id,
            {"action_id": action.id},
        )
        return repo.public_action_view(action)

    def reject_action(
        self, db: Session, action_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Отклонить бизнес-действие (status=rejected)."""
        action = self._require_action(db, action_id)
        if action.status == "applied":
            raise AIExecutiveError("Действие уже применено")
        repo.reject_action(db, action)
        self._write_audit(
            db,
            audit_actions.ACTION_BUSINESS_OS_REJECTED,
            action.project_id,
            user_id,
            {"action_id": action.id},
        )
        return repo.public_action_view(action)

    def apply_action(
        self, db: Session, action_id: int, confirmation: str = "", user_id: int | None = None
    ) -> dict[str, Any]:
        """Применить действие. ТОЛЬКО status=accepted И confirmation=APPLY_BUSINESS_ACTION.

        Меняет ЛИШЬ draft-стратегию и/или создаёт draft-кампанию. НЕ включает live, НЕ
        публикует, НЕ меняет CRM/бюджет.
        """
        action = self._require_action(db, action_id)
        if action.status != "accepted":
            raise AIExecutiveError("Сначала одобрите действие (accept)")
        if confirmation != APPLY_CONFIRMATION:
            raise AIExecutiveError("Требуется подтверждение APPLY_BUSINESS_ACTION")

        payload = dict(action.apply_payload or {})
        applied: dict[str, Any] = {"draft_strategy": False, "draft_campaign": False}
        if payload.get("draft_strategy"):
            applied["draft_strategy"] = self._apply_draft_strategy(db, action.project_id)
        if payload.get("draft_campaign"):
            applied["draft_campaign"] = self._apply_draft_campaign(
                db, action.project_id, payload["draft_campaign"], user_id
            )
        repo.apply_action(db, action)
        self._write_audit(
            db,
            audit_actions.ACTION_BUSINESS_OS_APPLIED,
            action.project_id,
            user_id,
            {"action_id": action.id, "applied": applied},
        )
        return {
            "action": repo.public_action_view(action),
            "applied": applied,
            "live_enabled": False,  # инвариант: apply НЕ включает live/публикацию/CRM/деньги
            "note": "Обновлён черновик стратегии/кампании. Live/CRM/бюджет/публикации не менялись.",
        }

    # ------------------------------------------------------------------ #
    # Внутреннее: сбор сигналов и apply-эффекты                          #
    # ------------------------------------------------------------------ #

    def _growth_analysis(self, db: Session, project_id: int, user_id: int | None) -> dict[str, Any]:
        """Анализ роста (reuse BusinessGrowthAgentService, v0.6.9)."""
        try:
            from app.services.business_growth_agent_service import BusinessGrowthAgentService

            return BusinessGrowthAgentService(settings=self._resolve_settings()).analyze_business(
                db, project_id, user_id=user_id
            )
        except Exception:  # noqa: BLE001 — вспомогательный слой не критичен
            return {}

    def _apply_draft_strategy(self, db: Session, project_id: int) -> bool:
        """Обновить draft-стратегию (ContentStrategyProfile). Без live/публикаций."""
        try:
            from app.services.content_strategist_service import ContentStrategistService

            ContentStrategistService(settings=self._resolve_settings()).build_strategy_snapshot(
                db, project_id
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("executive draft strategy failed: %s", type(exc).__name__)
            return False

    def _apply_draft_campaign(
        self, db: Session, project_id: int, spec: dict[str, Any], user_id: int | None
    ) -> bool:
        """Создать ЧЕРНОВИК кампании (status=draft). Не запускает, не публикует, не live."""
        try:
            from app.services.ai_campaign_manager_service import AICampaignManagerService

            goal = str(spec.get("goal") or "awareness")
            name = str(spec.get("name") or "Кампания роста")[:255]
            AICampaignManagerService(settings=self._resolve_settings()).create_campaign(
                db, project_id, name=name, goal=goal, user_id=user_id
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("executive draft campaign failed: %s", type(exc).__name__)
            return False

    # --- деривация текста плана ---

    @staticmethod
    def _executive_summary(state: dict[str, Any]) -> str:
        sales = state.get("sales_state", {})
        revenue = state.get("revenue_state", {})
        leads = int(sales.get("leads", 0) or 0)
        total_revenue = float(revenue.get("total_revenue", 0) or 0)
        conversion = float(revenue.get("conversion_rate", 0) or 0)
        if total_revenue <= 0:
            return "Главная точка роста — получить первые продажи из контента и зафиксировать лиды."
        if leads == 0:
            return "Главная точка роста — увеличить количество лидов из контента."
        if conversion < 0.2:
            return "Главная точка роста — повысить конверсию лид→сделка (офферы и CTA)."
        return "Фокус — масштабировать работающие темы и каналы, удерживая конверсию."

    @staticmethod
    def _plan_confidence(state: dict[str, Any], opportunities: list[dict[str, Any]]) -> float:
        base = min(90.0, 40.0 + 10.0 * len(opportunities))
        if float(state.get("growth_score", 0) or 0) > 0:
            base = min(95.0, base + 5.0)
        return round(base, 1)

    @staticmethod
    def _expected_outcomes(state: dict[str, Any]) -> dict[str, Any]:
        return {
            "business_health_target": min(100.0, float(state.get("business_health", 0)) + 15.0),
            "focus": "рост лидов и выручки без роста рисков",
        }

    # ------------------------------------------------------------------ #
    # Инфраструктура                                                     #
    # ------------------------------------------------------------------ #

    def _require_project(self, db: Session, project_id: int) -> Any:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise AIExecutiveError(f"Проект id={project_id} не найден")
        return project

    def _require_action(self, db: Session, action_id: int) -> BusinessAction:
        action = repo.get_action(db, action_id)
        if action is None:
            raise AIExecutiveError("Действие не найдено")
        return action

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
            entity_type="ai_executive_plan",
            metadata=metadata,
        )


def get_ai_executive_service() -> AIExecutiveService:
    """DI-фабрика Autonomous Business OS / AI Executive Layer."""
    return AIExecutiveService()
