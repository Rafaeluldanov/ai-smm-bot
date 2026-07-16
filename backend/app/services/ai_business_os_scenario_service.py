"""AIBusinessOSScenarioService — E2E scenario runner для MVP Testing (v0.9.0).

Прогоняет всю AI-цепочку на изолированном demo-проекте и фиксирует PASS/FAIL по каждому этапу:
Business Goal → Decision → Forecast → Planner → Execution → Performance → Learning → Optimization →
Governance. Каждый слой вызывается своим advisory-методом в try/except; бизнес/CRM/workflow не
затрагиваются.

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- работает только при demo_mode=true; все вызываемые слои — advisory (не публикуют, не выполняют
  workflow, не меняют CRM/бюджет, не шлют сообщений); НЕ создаёт реальных пользователей/платежей;
- сценарий прогоняется на ОТДЕЛЬНОМ demo-проекте (изоляция), падение любого этапа не роняет прогон;
- секретов нет; бесплатно (0 units); изменения (scenario_started/completed) → AuditLog.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import demo_testing_repository as repo
from app.services import audit_log_service as audit_actions
from app.services.ai_business_os_demo_service import (
    DEMO_COMPANY_PROFILE,
    AIBusinessOSDemoError,
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.demo_scenario import DemoScenario
    from app.models.demo_workspace import DemoWorkspace
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

# Полный порядок этапов пайплайна AI Business OS.
PIPELINE_STAGES: tuple[str, ...] = (
    "decision",
    "forecast",
    "planner",
    "execution",
    "performance",
    "learning",
    "optimization",
    "governance",
)

# Проблемное состояние по типу сценария (сидируется перед learning для детерминированного цикла).
_SCENARIO_PROBLEM: dict[str, dict[str, str]] = {
    "growth": {"metric": "revenue", "title": "Выручка ниже цели (5М из 10М)", "impact": "high"},
    "recovery": {"metric": "sales", "title": "Продажи упали на 20%", "impact": "critical"},
    "optimization": {
        "metric": "execution",
        "title": "Процессы работают медленно (блокеры)",
        "impact": "high",
    },
}


class AIBusinessOSScenarioService:
    """E2E-прогон AI-цепочки на demo-проекте: этап за этапом с фиксацией PASS/FAIL."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Публичные сценарии                                                 #
    # ------------------------------------------------------------------ #

    def run_growth_scenario(
        self, db: Session, workspace_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Рост: полный цикл Goal → Decision → … → Governance."""
        return self.run_scenario(db, workspace_id, "growth", user_id=user_id)

    def run_recovery_scenario(
        self, db: Session, workspace_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Восстановление: продажи упали на 20% — найти проблему, предложить решение, план."""
        return self.run_scenario(db, workspace_id, "recovery", user_id=user_id)

    def run_optimization_scenario(
        self, db: Session, workspace_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Оптимизация: процессы медленны — паттерн → Improvement → Optimization → Governance."""
        return self.run_scenario(db, workspace_id, "optimization", user_id=user_id)

    def run_scenario(
        self, db: Session, workspace_id: int, scenario_type: str, user_id: int | None = None
    ) -> dict[str, Any]:
        """Прогнать demo-сценарий: собрать demo-проект, пройти все этапы, сохранить результат."""
        self._require_demo_mode()
        from app.models.demo_scenario import SCENARIO_TYPES

        if scenario_type not in SCENARIO_TYPES:
            raise AIBusinessOSDemoError(f"Неизвестный тип сценария: {scenario_type}")
        workspace = self._require_workspace(db, workspace_id)

        scenario = repo.create_scenario(
            db,
            workspace_id=workspace.id,
            scenario_type=scenario_type,
            status="running",
            input_data={"scenario_type": scenario_type, "company": DEMO_COMPANY_PROFILE},
        )
        self._write_audit(
            db,
            audit_actions.ACTION_DEMO_SCENARIO_STARTED,
            workspace.account_id,
            user_id,
            scenario.id,
            {"scenario_type": scenario_type},
        )

        try:
            project_id = self._create_demo_project(db, workspace, scenario)
            stages = self._run_pipeline(db, project_id, workspace.account_id, scenario_type)
            passed = sum(1 for s in stages if s["status"] == "pass")
            produced = sum(1 for s in stages if s["produced"])
            total = len(stages)
            score = round((0.7 * passed + 0.3 * produced) / total * 100, 1) if total else 0.0
            result_data = {
                "project_id": project_id,
                "scenario_type": scenario_type,
                "problem": _SCENARIO_PROBLEM.get(scenario_type, {}),
                "stages": stages,
                "passed": passed,
                "produced": produced,
                "total": total,
                "score": score,
            }
            status = "completed"
        except Exception as exc:  # noqa: BLE001 — прогон не должен ронять запрос
            logger.warning("demo scenario run failed: %s", type(exc).__name__)
            db.rollback()  # сброс возможно «отравленной» сессии перед сохранением
            result_data = {
                "scenario_type": scenario_type,
                "error": type(exc).__name__,
                "stages": [],
            }
            score = 0.0
            status = "failed"

        # save_result сам коммитит; сессия могла быть отравлена проглоченной ошибкой этапа —
        # защищаемся, чтобы прогон никогда не ронял запрос (fail closed → status=failed).
        try:
            repo.save_result(db, scenario, status=status, result_data=result_data, score=score)
        except Exception as exc:  # noqa: BLE001
            logger.warning("demo save_result failed: %s", type(exc).__name__)
            db.rollback()
            try:
                repo.save_result(
                    db, scenario, status="failed", result_data={"error": "save_failed"}, score=0.0
                )
            except Exception:  # noqa: BLE001 — крайний случай: не роняем запрос
                db.rollback()
        self._write_audit(
            db,
            audit_actions.ACTION_DEMO_SCENARIO_COMPLETED,
            workspace.account_id,
            user_id,
            scenario.id,
            {"status": scenario.status, "score": scenario.score},
        )
        return repo.public_scenario_view(scenario)

    # ------------------------------------------------------------------ #
    # Пайплайн                                                           #
    # ------------------------------------------------------------------ #

    def _run_pipeline(
        self, db: Session, project_id: int, account_id: int | None, scenario_type: str
    ) -> list[dict[str, Any]]:
        """Пройти все этапы AI-цепочки на demo-проекте (advisory-вызовы, каждый в try/except)."""
        from app.services.ai_business_forecasting_service import AIBusinessForecastingService
        from app.services.ai_business_planner_service import AIBusinessPlannerService
        from app.services.ai_continuous_improvement_service import AIContinuousImprovementService
        from app.services.ai_decision_engine_service import AIDecisionEngineService
        from app.services.ai_execution_coordinator_service import AIExecutionCoordinatorService
        from app.services.ai_optimization_engine_service import AIOptimizationEngineService
        from app.services.ai_optimization_governance_service import (
            AIOptimizationGovernanceService,
        )
        from app.services.ai_performance_intelligence_service import (
            AIPerformanceIntelligenceService,
        )

        settings = self._resolve_settings()
        decision = AIDecisionEngineService(settings=settings)
        forecast = AIBusinessForecastingService(settings=settings)
        planner = AIBusinessPlannerService(settings=settings)
        execution = AIExecutionCoordinatorService(settings=settings)
        performance = AIPerformanceIntelligenceService(settings=settings)
        learning = AIContinuousImprovementService(settings=settings)
        optimization = AIOptimizationEngineService(settings=settings)
        governance = AIOptimizationGovernanceService(settings=settings)

        ctx: dict[str, Any] = {}
        goal = self._demo_goal()

        def _decision() -> dict[str, Any]:
            return decision.create_decision(
                db, project_id, decision_type="growth", title="Demo: стратегическое решение"
            )

        def _forecast() -> dict[str, Any]:
            return forecast.create_forecast(db, project_id, title="Demo: прогноз выручки")

        def _planner() -> dict[str, Any]:
            created_goal = planner.create_business_goal(
                db,
                project_id,
                goal_type=goal["goal_type"],
                title=goal["title"],
                current_value=goal["current_value"],
                target_value=goal["target_value"],
            )
            plan = planner.generate_strategic_plan(db, created_goal["id"])
            # generate_strategic_plan возвращает {"plan": {...}, "objectives": [...]}.
            plan_id = plan["plan"]["id"]
            approved = planner.approve_plan(db, plan_id)
            ctx["strategic_plan_id"] = approved["id"]
            return approved

        def _execution() -> dict[str, Any]:
            plan_id = ctx.get("strategic_plan_id")
            if plan_id is None:
                raise RuntimeError("нет одобрённого стратегического плана")
            exec_plan = execution.create_execution_plan(db, project_id, strategic_plan_id=plan_id)
            return execution.generate_execution(db, exec_plan["id"])

        def _performance() -> dict[str, Any]:
            return performance.create_snapshot(db, project_id)

        def _learning() -> dict[str, Any]:
            self._seed_problem(db, project_id, account_id, scenario_type)
            return learning.run_learning_cycle(db, project_id)

        def _optimization() -> dict[str, Any]:
            return optimization.run_optimization_cycle(db, project_id)

        def _governance() -> dict[str, Any]:
            return governance.run_governance_cycle(db, project_id)

        stage_fns: list[tuple[str, Callable[[], dict[str, Any]], Callable[[Any], bool]]] = [
            ("decision", _decision, lambda o: bool(o and o.get("id"))),
            ("forecast", _forecast, lambda o: bool(o and o.get("id"))),
            ("planner", _planner, lambda o: bool(o and o.get("id"))),
            ("execution", _execution, lambda o: bool(o and o.get("objectives") is not None)),
            ("performance", _performance, lambda o: bool(o and o.get("id"))),
            ("learning", _learning, lambda o: bool(o and o.get("improvements"))),
            ("optimization", _optimization, lambda o: bool(o and o.get("optimizations"))),
            ("governance", _governance, lambda o: bool(o and o.get("governances"))),
        ]
        return [self._run_stage(db, name, fn, produced) for name, fn, produced in stage_fns]

    @staticmethod
    def _run_stage(
        db: Session,
        name: str,
        fn: Callable[[], dict[str, Any]],
        produced_fn: Callable[[Any], bool],
    ) -> dict[str, Any]:
        """Выполнить этап пайплайна: PASS если без исключения, иначе FAIL (не роняет прогон)."""
        try:
            out = fn()
            return {
                "stage": name,
                "status": "pass",
                "produced": bool(produced_fn(out)),
                "detail": _summarize(out),
            }
        except Exception as exc:  # noqa: BLE001 — падение этапа не роняет прогон
            logger.warning("demo stage %s failed: %s", name, type(exc).__name__)
            db.rollback()  # сброс возможно «отравленной» сессии перед следующим этапом
            return {
                "stage": name,
                "status": "fail",
                "produced": False,
                "detail": f"{type(exc).__name__}: {str(exc)[:120]}",
            }

    def _seed_problem(
        self, db: Session, project_id: int, account_id: int | None, scenario_type: str
    ) -> None:
        """Зафиксировать проблемное состояние (Performance snapshot+deviation) для обучения."""
        problem = _SCENARIO_PROBLEM.get(scenario_type, _SCENARIO_PROBLEM["growth"])
        goal = self._demo_goal()
        try:
            from app.repositories import performance_repository as perf_repo

            snapshot = perf_repo.create_snapshot(
                db,
                project_id=project_id,
                account_id=account_id,
                status="critical",
                performance_score=25.0,
                target_state={"revenue": goal["target_value"]},
                actual_state={"revenue": goal["current_value"]},
            )
            perf_repo.create_deviation(
                db,
                snapshot_id=snapshot.id,
                metric=problem["metric"],
                title=problem["title"],
                impact=problem["impact"],
            )
        except Exception as exc:  # noqa: BLE001 — сидирование не должно ронять прогон
            logger.warning("demo seed problem failed: %s", type(exc).__name__)

    # ------------------------------------------------------------------ #
    # Внутреннее                                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _demo_goal() -> dict[str, Any]:
        return {
            "goal_type": "revenue",
            "title": "Увеличить выручку с 5 млн до 10 млн",
            "current_value": float(DEMO_COMPANY_PROFILE["monthly_revenue"]),
            "target_value": float(DEMO_COMPANY_PROFILE["growth_target"]),
        }

    def _create_demo_project(
        self, db: Session, workspace: DemoWorkspace, scenario: DemoScenario
    ) -> int:
        """Создать ИЗОЛИРОВАННЫЙ demo-проект под прогон (не реальный бизнес-проект)."""
        from app.repositories import project_repository
        from app.schemas.project import ProjectCreate

        slug = f"demo-{scenario.id}"
        project = project_repository.create_project(
            db, ProjectCreate(name=f"[DEMO] {workspace.company_name} #{scenario.id}", slug=slug)
        )
        project.account_id = workspace.account_id
        db.commit()
        db.refresh(project)
        scenario.input_data = {**dict(scenario.input_data or {}), "project_id": project.id}
        db.commit()
        return project.id

    def _require_demo_mode(self) -> None:
        if not self._resolve_settings().demo_mode_effective:
            raise AIBusinessOSDemoError("DEMO-режим выключен (demo_mode=false)")

    def _require_workspace(self, db: Session, workspace_id: int) -> DemoWorkspace:
        workspace = repo.get_workspace(db, workspace_id)
        if workspace is None:
            raise AIBusinessOSDemoError("Demo-воркспейс не найден")
        return workspace

    def _resolve_settings(self) -> Settings:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _write_audit(
        self,
        db: Session,
        action: str,
        account_id: int | None,
        user_id: int | None,
        entity_id: int | None,
        metadata: dict[str, Any],
    ) -> None:
        if self._audit_svc is None:
            from app.services.audit_log_service import AuditLogService

            self._audit_svc = AuditLogService(self._resolve_settings())
        self._audit_svc.record(
            db,
            action,
            account_id=account_id,
            user_id=user_id,
            project_id=None,
            entity_type="demo_scenario",
            entity_id=entity_id,
            metadata=metadata,
        )


def _summarize(out: Any) -> str:
    """Короткая сводка результата этапа (без секретов)."""
    if not isinstance(out, dict):
        return ""
    if "id" in out:
        return f"id={out['id']}"
    for key in ("optimizations", "governances", "improvements", "objectives"):
        value = out.get(key)
        if isinstance(value, list):
            return f"{key}={len(value)}"
    return "ok"


def get_ai_business_os_scenario_service() -> AIBusinessOSScenarioService:
    """DI-фабрика AI Business OS Scenario runner."""
    return AIBusinessOSScenarioService()
