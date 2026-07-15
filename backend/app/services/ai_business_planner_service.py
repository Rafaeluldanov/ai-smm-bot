"""AIBusinessPlannerService — AI Business Planner (v0.7.7).

Превращает бизнес-цель владельца в стратегический план: анализирует текущее состояние,
сравнивает с прогнозом (Forecasting), находит gap, строит стратегию, квартальные цели, KPI и
roadmap; по одобрению может создать ЧЕРНОВИК процесса (Workflow Manager).

Поток: **Business Goal → Gap Analysis → Strategic Plan → Quarter Objectives → KPI →
Milestones → Workflow Draft**.

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- это planning-слой: только планирует и советует;
- НЕ выполняет план автоматически, НЕ меняет бизнес/CRM/бюджет, НЕ запускает рекламу, НЕ публикует;
- approve меняет ТОЛЬКО статус (generated→approved); convert возможен ТОЛЬКО при status=approved и
  создаёт лишь ЧЕРНОВИК процесса (draft workflow), процессы/CRM/бюджет не запускаются;
- строго per-project; секретов нет; бесплатно (0 units);
- каждое изменение (goal/plan/objective/milestone/workflow.draft) пишется в AuditLog.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import business_planner_repository as repo
from app.repositories import project_repository
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.business_goal import BusinessGoal
    from app.models.strategic_plan import StrategicPlan
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

# Кварталы плана.
_QUARTERS: tuple[str, ...] = ("Q1", "Q2", "Q3", "Q4")

# Тип цели → метрика baseline (для current-value, если не задан вручную).
_GOAL_TO_METRIC: dict[str, str] = {
    "revenue": "revenue",
    "growth": "growth_score",
    "sales": "leads",
    "marketing": "traffic",
    "efficiency": "efficiency",
    "operational": "health_score",
}
# Тип цели → тип процесса (для draft workflow при convert).
_GOAL_TO_WORKFLOW: dict[str, str] = {
    "revenue": "sales",
    "growth": "growth",
    "sales": "sales",
    "marketing": "marketing",
    "efficiency": "operational",
    "operational": "operational",
}

# Шаблон квартальных фокусов: (title, description, priority). KPI считается из gap.
_QUARTER_TEMPLATE: tuple[tuple[str, str, str], ...] = (
    ("Нарастить поток лидов", "Увеличить входящий поток из контента", "high"),
    ("Поднять конверсию в продажи", "Улучшить путь лид → сделка", "high"),
    ("Масштабировать работающие каналы", "Усилить каналы, дающие результат", "medium"),
    ("Оптимизировать и закрепить рост", "Юнит-экономика и удержание результата", "medium"),
)

# Подтверждение, обязательное для конвертации плана в черновик процесса.
CONVERT_CONFIRMATION = "CONVERT_PLAN"


class AIBusinessPlannerError(Exception):
    """Ошибка Business Planner (нет проекта/цели/плана/подтверждения) — API → 400/404."""


class AIBusinessPlannerService:
    """AI-планировщик: goal → gap → plan → objectives → KPI → milestones → workflow draft."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Цели: создание / чтение                                            #
    # ------------------------------------------------------------------ #

    def create_business_goal(
        self,
        db: Session,
        project_id: int,
        *,
        goal_type: str,
        title: str,
        description: str | None = None,
        target_value: float = 0.0,
        current_value: float = 0.0,
        target_date: datetime | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Создать бизнес-цель владельца."""
        from app.models.business_goal import GOAL_TYPES

        self._require_project(db, project_id)
        if goal_type not in GOAL_TYPES:
            raise AIBusinessPlannerError("Неизвестный тип цели")
        clean_title = (title or "").strip()
        if not clean_title:
            raise AIBusinessPlannerError("Укажите название цели")

        goal = repo.create_goal(
            db,
            project_id=project_id,
            account_id=self._account_id(db, project_id),
            goal_type=goal_type,
            title=clean_title,
            description=description,
            target_value=target_value,
            current_value=current_value,
            target_date=target_date,
        )
        self._write_audit(
            db,
            audit_actions.ACTION_GOAL_CREATED,
            project_id,
            user_id,
            goal.id,
            {"goal_type": goal_type},
            entity_type="business_goal",
        )
        return repo.public_goal_view(goal)

    def list_goals(
        self, db: Session, project_id: int, status: str | None = None
    ) -> list[dict[str, Any]]:
        """Список целей проекта (по статусу)."""
        self._require_project(db, project_id)
        return [repo.public_goal_view(g) for g in repo.list_goals(db, project_id, status=status)]

    def get_goal(self, db: Session, goal_id: int) -> dict[str, Any]:
        """Цель + планы."""
        goal = self._require_goal(db, goal_id)
        return {
            "goal": repo.public_goal_view(goal),
            "plans": [repo.public_plan_view(p) for p in repo.list_plans(db, goal_id)],
        }

    def get_summary(self, db: Session, project_id: int) -> dict[str, Any]:
        """Сводка Business Planner (для UI-состояния)."""
        self._require_project(db, project_id)
        return repo.build_planner_summary(db, project_id)

    # ------------------------------------------------------------------ #
    # Gap-анализ                                                          #
    # ------------------------------------------------------------------ #

    def analyze_gap(self, db: Session, goal_id: int) -> dict[str, Any]:
        """Сравнить текущее состояние с целью: {current, target, gap, gap_percent}."""
        goal = self._require_goal(db, goal_id)
        return self._gap_for_goal(db, goal)

    def _gap_for_goal(self, db: Session, goal: BusinessGoal) -> dict[str, Any]:
        current = float(goal.current_value or 0.0)
        if current <= 0:
            current = self._current_from_baseline(db, goal.project_id, goal.goal_type)
        target = float(goal.target_value or 0.0)
        gap = round(target - current, 2)
        gap_percent = round((gap / target * 100.0), 1) if target > 0 else 0.0
        return {
            "metric": _GOAL_TO_METRIC.get(goal.goal_type, goal.goal_type),
            "current": round(current, 2),
            "target": round(target, 2),
            "gap": gap,
            "gap_percent": gap_percent,
        }

    def _current_from_baseline(self, db: Session, project_id: int, goal_type: str) -> float:
        """Текущее значение метрики из Business Forecasting baseline (если не задано вручную)."""
        try:
            from app.services.ai_business_forecasting_service import (
                AIBusinessForecastingService,
            )

            baseline = AIBusinessForecastingService(
                settings=self._resolve_settings()
            ).collect_business_baseline(db, project_id)
            metric = _GOAL_TO_METRIC.get(goal_type, goal_type)
            return float(baseline.get(metric, 0.0) or 0.0)
        except Exception as exc:  # noqa: BLE001 — нижний слой не должен ронять gap
            logger.warning("planner baseline current failed: %s", type(exc).__name__)
            return 0.0

    # ------------------------------------------------------------------ #
    # Генерация плана                                                     #
    # ------------------------------------------------------------------ #

    def generate_strategic_plan(
        self, db: Session, goal_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Построить стратегический план: gap → стратегия → кварталы → KPI → вехи → уверенность.

        Использует Business Forecast / Decision Engine / Operations. НЕ выполняет план.
        """
        goal = self._require_goal(db, goal_id)
        gap = self._gap_for_goal(db, goal)
        forecast_signals = self._forecast_signals(db, goal.project_id)
        decision_signals = self._decision_signals(db, goal.project_id)

        confidence = self.calculate_plan_confidence(
            forecast_confidence=float(forecast_signals.get("confidence", 0.0)),
            data_quality=self._data_quality(gap, forecast_signals),
            strategy_confidence=self._strategy_confidence(gap),
        )
        strategy = self._build_strategy(goal, gap, forecast_signals, decision_signals)
        summary = self._plan_summary(goal, gap, confidence)

        plan = repo.create_plan(
            db,
            goal_id=goal_id,
            title=f"План: {goal.title}",
            status="generated",
            summary=summary,
            gap_analysis=gap,
            strategy=strategy,
            confidence_score=confidence,
        )
        self.generate_quarter_objectives(db, plan.id, goal, gap, user_id)
        self._write_audit(
            db,
            audit_actions.ACTION_PLAN_GENERATED,
            goal.project_id,
            user_id,
            plan.id,
            {"goal_id": goal_id, "confidence": confidence},
            entity_type="strategic_plan",
        )
        return self.get_plan(db, plan.id)

    def generate_quarter_objectives(
        self,
        db: Session,
        plan_id: int,
        goal: BusinessGoal | None = None,
        gap: dict[str, Any] | None = None,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Создать квартальные цели Q1–Q4 с KPI (доля закрытия gap по кварталу) + вехи."""
        plan = self._require_plan(db, plan_id)
        goal = goal if goal is not None else self._require_goal(db, plan.goal_id)
        gap = gap if gap is not None else self._gap_for_goal(db, goal)
        current = float(gap.get("current", 0.0))
        target = float(gap.get("target", 0.0))
        metric = str(gap.get("metric", goal.goal_type))

        repo.delete_objectives(db, plan_id)  # пересоздание при повторной генерации
        created: list[dict[str, Any]] = []
        for idx, (title, description, priority) in enumerate(_QUARTER_TEMPLATE, start=1):
            # Линейное распределение цели по кварталам (доля закрытия gap).
            quarter_target = round(current + (target - current) * (idx / 4.0), 2)
            objective = repo.create_objective(
                db,
                plan_id=plan_id,
                quarter=_QUARTERS[idx - 1],
                title=title,
                description=description,
                kpi=[{"metric": metric, "quarter_target": quarter_target}],
                priority=priority,
                status="planned",
            )
            self.create_milestones(db, objective.id, title, quarter_target, metric, user_id)
            created.append(repo.public_objective_view(objective))
        self._write_audit(
            db,
            audit_actions.ACTION_PLAN_OBJECTIVE_CREATED,
            goal.project_id,
            user_id,
            plan_id,
            {"objectives": len(created)},
            entity_type="strategic_plan",
        )
        return created

    def create_milestones(
        self,
        db: Session,
        objective_id: int,
        quarter_title: str,
        quarter_target: float,
        metric: str,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Создать вехи квартальной цели (планирование + выполнение/замер)."""
        objective = repo.get_objective(db, objective_id)
        if objective is None:
            raise AIBusinessPlannerError("Квартальная цель не найдена")
        specs = (
            (f"Спланировать: {quarter_title}", "Детализировать шаги и ответственных"),
            (
                f"Достичь {metric} ≈ {quarter_target}",
                "Выполнить план квартала и измерить результат",
            ),
        )
        created: list[dict[str, Any]] = []
        for title, description in specs:
            milestone = repo.create_milestone(
                db, objective_id=objective_id, title=title, description=description
            )
            created.append(repo.public_milestone_view(milestone))
        plan = repo.get_plan(db, objective.plan_id)
        if plan is not None:
            goal = repo.get_goal(db, plan.goal_id)
            if goal is not None:
                self._write_audit(
                    db,
                    audit_actions.ACTION_PLAN_MILESTONE_CREATED,
                    goal.project_id,
                    user_id,
                    objective_id,
                    {"milestones": len(created)},
                    entity_type="quarter_objective",
                )
        return created

    def calculate_plan_confidence(
        self,
        *,
        forecast_confidence: float,
        data_quality: float,
        strategy_confidence: float,
    ) -> float:
        """Уверенность плана 0..100: прогноз + качество данных + осуществимость стратегии."""
        raw = (
            0.4 * self._clamp(forecast_confidence, 0.0, 100.0)
            + 0.3 * self._clamp(data_quality, 0.0, 100.0)
            + 0.3 * self._clamp(strategy_confidence, 0.0, 100.0)
        )
        return round(self._clamp(raw, 0.0, 100.0), 1)

    # ------------------------------------------------------------------ #
    # Чтение плана / объяснение                                          #
    # ------------------------------------------------------------------ #

    def get_plan(self, db: Session, plan_id: int) -> dict[str, Any]:
        """План + квартальные цели + вехи."""
        plan = self._require_plan(db, plan_id)
        objectives: list[dict[str, Any]] = []
        for objective in repo.list_objectives(db, plan_id):
            view = repo.public_objective_view(objective)
            view["milestones"] = [
                repo.public_milestone_view(m) for m in repo.list_milestones(db, objective.id)
            ]
            objectives.append(view)
        return {"plan": repo.public_plan_view(plan), "objectives": objectives}

    def get_objectives(self, db: Session, plan_id: int) -> list[dict[str, Any]]:
        """Квартальные цели плана (+ вехи)."""
        objectives: list[dict[str, Any]] = self.get_plan(db, plan_id)["objectives"]
        return objectives

    def explain_plan(self, db: Session, plan_id: int) -> dict[str, Any]:
        """Объяснить владельцу: почему AI выбрал этот план."""
        plan = self._require_plan(db, plan_id)
        gap = dict(plan.gap_analysis or {})
        reasons: list[str] = [
            f"Цель: {gap.get('metric', '—')} {gap.get('current', 0)} → {gap.get('target', 0)} "
            f"(gap {gap.get('gap', 0)}, {gap.get('gap_percent', 0)}%).",
            f"Стратегия: {(plan.strategy or {}).get('approach', 'поэтапное закрытие gap')}.",
            f"Уверенность плана: {round(float(plan.confidence_score or 0.0), 1)}/100 "
            f"(прогноз + качество данных + осуществимость).",
            "План — рекомендация; выполняется только после одобрения владельцем.",
        ]
        return {"plan_id": plan_id, "reasons": reasons}

    # ------------------------------------------------------------------ #
    # Approve / Convert                                                  #
    # ------------------------------------------------------------------ #

    def approve_plan(self, db: Session, plan_id: int, user_id: int | None = None) -> dict[str, Any]:
        """Одобрить план (status=approved). НЕ выполняет."""
        plan = self._require_plan(db, plan_id)
        if plan.status not in ("generated", "reviewed"):
            raise AIBusinessPlannerError("Сначала сгенерируйте план (generate)")
        repo.update_plan(db, plan, status="approved")
        goal = self._require_goal(db, plan.goal_id)
        self._write_audit(
            db,
            audit_actions.ACTION_PLAN_APPROVED,
            goal.project_id,
            user_id,
            plan.id,
            {},
            entity_type="strategic_plan",
        )
        return repo.public_plan_view(plan)

    def convert_to_workflow(
        self, db: Session, plan_id: int, confirmation: str = "", user_id: int | None = None
    ) -> dict[str, Any]:
        """Создать ЧЕРНОВИК процесса из одобренного плана. ТОЛЬКО status=approved И подтверждение.

        Создаёт лишь draft workflow. НЕ запускает процессы, НЕ меняет CRM/бюджет, live off.
        """
        plan = self._require_plan(db, plan_id)
        if plan.status != "approved":
            raise AIBusinessPlannerError("Сначала одобрите план (approve)")
        if confirmation != CONVERT_CONFIRMATION:
            raise AIBusinessPlannerError("Требуется подтверждение CONVERT_PLAN")
        goal = self._require_goal(db, plan.goal_id)
        draft_created = self._create_draft_workflow(db, goal, plan, user_id)
        self._write_audit(
            db,
            audit_actions.ACTION_PLAN_WORKFLOW_DRAFT_CREATED,
            goal.project_id,
            user_id,
            plan.id,
            {"draft_workflow": draft_created},
            entity_type="strategic_plan",
        )
        return {
            "plan": repo.public_plan_view(plan),
            "converted": {"draft_workflow": draft_created},
            "live_enabled": False,  # convert НЕ запускает процессы/CRM/бюджет/публикации/live
            "note": "Создан черновик процесса. Процессы/CRM/бюджет/публикации не запускались.",
        }

    def _create_draft_workflow(
        self, db: Session, goal: BusinessGoal, plan: StrategicPlan, user_id: int | None
    ) -> bool:
        """Создать draft workflow из плана (status=draft, не запускает)."""
        try:
            from app.services.ai_workflow_manager_service import AIWorkflowManagerService

            workflow_type = _GOAL_TO_WORKFLOW.get(goal.goal_type, "custom")
            AIWorkflowManagerService(settings=self._resolve_settings()).create_workflow_from_goal(
                db,
                goal.project_id,
                name=goal.title[:255],
                workflow_type=workflow_type,
                goal=goal.description or goal.title,
                description=plan.summary,
                target_value=float(goal.target_value or 0.0),
                status="draft",
                user_id=user_id,
            )
            return True
        except Exception as exc:  # noqa: BLE001 — не роняем convert из-за нижнего слоя
            logger.warning("planner draft workflow failed: %s", type(exc).__name__)
            return False

    # ------------------------------------------------------------------ #
    # Сигналы смежных слоёв + построение стратегии                        #
    # ------------------------------------------------------------------ #

    def _forecast_signals(self, db: Session, project_id: int) -> dict[str, Any]:
        """Сигналы прогноза (Business Forecasting): confidence + последний outlook."""
        try:
            from app.repositories import business_forecast_repository as fc_repo

            latest = fc_repo.get_latest_forecast(db, project_id)
            if latest is not None:
                return {
                    "confidence": float(latest.confidence_score or 0.0),
                    "risk_level": latest.risk_level,
                    "has_forecast": True,
                }
        except Exception as exc:  # noqa: BLE001
            logger.warning("planner forecast signal failed: %s", type(exc).__name__)
        return {"confidence": 0.0, "risk_level": "medium", "has_forecast": False}

    def _decision_signals(self, db: Session, project_id: int) -> dict[str, Any]:
        """Сигналы Decision Engine: число рекомендованных решений (фокус стратегии)."""
        try:
            from app.repositories import decision_repository as decision_repo

            decisions = decision_repo.list_decisions(db, project_id, limit=20)
            recommended = sum(1 for d in decisions if d.status in ("recommended", "accepted"))
            return {"decisions": len(decisions), "recommended": recommended}
        except Exception as exc:  # noqa: BLE001
            logger.warning("planner decision signal failed: %s", type(exc).__name__)
            return {"decisions": 0, "recommended": 0}

    def _build_strategy(
        self,
        goal: BusinessGoal,
        gap: dict[str, Any],
        forecast_signals: dict[str, Any],
        decision_signals: dict[str, Any],
    ) -> dict[str, Any]:
        gap_percent = float(gap.get("gap_percent", 0.0) or 0.0)
        if gap_percent <= 0:
            approach = "Удерживать результат: цель достигнута или почти достигнута"
        elif gap_percent < 50:
            approach = "Поэтапное закрытие gap через усиление работающих каналов"
        else:
            approach = "Агрессивный рост: расширение каналов + новые кампании"
        return {
            "approach": approach,
            "focus_metric": gap.get("metric", goal.goal_type),
            "gap_percent": gap_percent,
            "forecast_aligned": bool(forecast_signals.get("has_forecast")),
            "decision_support": decision_signals.get("recommended", 0),
            "phases": list(_QUARTERS),
        }

    @staticmethod
    def _plan_summary(goal: BusinessGoal, gap: dict[str, Any], confidence: float) -> str:
        return (
            f"План достижения цели «{goal.title}»: закрыть gap "
            f"{gap.get('gap', 0)} ({gap.get('gap_percent', 0)}%) за 4 квартала. "
            f"Уверенность {confidence}/100. План — рекомендация, не гарантия."
        )

    @staticmethod
    def _data_quality(gap: dict[str, Any], forecast_signals: dict[str, Any]) -> float:
        score = 0.0
        if float(gap.get("current", 0.0) or 0.0) > 0:
            score += 40.0
        if float(gap.get("target", 0.0) or 0.0) > 0:
            score += 40.0
        if forecast_signals.get("has_forecast"):
            score += 20.0
        return score

    @staticmethod
    def _strategy_confidence(gap: dict[str, Any]) -> float:
        """Осуществимость: меньший gap% → выше уверенность."""
        gap_percent = abs(float(gap.get("gap_percent", 0.0) or 0.0))
        return max(0.0, 100.0 - min(100.0, gap_percent))

    # ------------------------------------------------------------------ #
    # Инфраструктура                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, float(value)))

    def _require_project(self, db: Session, project_id: int) -> Any:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise AIBusinessPlannerError(f"Проект id={project_id} не найден")
        return project

    def _require_goal(self, db: Session, goal_id: int) -> BusinessGoal:
        goal = repo.get_goal(db, goal_id)
        if goal is None:
            raise AIBusinessPlannerError("Цель не найдена")
        return goal

    def _require_plan(self, db: Session, plan_id: int) -> StrategicPlan:
        plan = repo.get_plan(db, plan_id)
        if plan is None:
            raise AIBusinessPlannerError("План не найден")
        return plan

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
        entity_id: int | None,
        metadata: dict[str, Any],
        *,
        entity_type: str = "business_goal",
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
            entity_type=entity_type,
            entity_id=entity_id,
            metadata=metadata,
        )


def get_ai_business_planner_service() -> AIBusinessPlannerService:
    """DI-фабрика AI Business Planner."""
    return AIBusinessPlannerService()
