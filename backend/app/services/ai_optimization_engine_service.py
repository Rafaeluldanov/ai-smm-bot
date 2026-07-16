"""AIOptimizationEngineService — AI Autonomous Optimization Engine (v0.8.1).

Превращает Improvement Backlog (v0.8.0) в систему оценки, приоритизации и проверки улучшений:
считает Optimization Score, ранжирует улучшения, формирует эксперименты-гипотезы, измеряет и
валидирует итог и возвращает результат обратно в Learning Engine (LearningEvent).

Поток: **Improvement Item → Optimization Score → Experiment → Measurement → Validation →
Learning Update**.

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- это optimization/аналитический слой: только оценивает, приоритизирует и проверяет;
- НЕ применяет улучшения, НЕ меняет бизнес/KPI/CRM/бюджет, НЕ выполняет задачи, НЕ запускает
  рекламу, НЕ публикует; эксперименты создаются как ЧЕРНОВИК (draft) и НЕ запускаются автоматически;
- ВЕСЬ сбор смежных слоёв (Improvement / Performance / Execution) — READ-ONLY в try/except;
- строго per-project; секретов нет; бесплатно (0 units);
- каждое изменение (optimization.created/prioritized, optimization.experiment_created/completed/
  validated) → AuditLog.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import continuous_improvement_repository as ci_repo
from app.repositories import optimization_repository as repo
from app.repositories import project_repository
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.improvement_item import ImprovementItem
    from app.models.optimization_experiment import OptimizationExperiment
    from app.models.optimization_item import OptimizationItem
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

# Итог валидации → тип события обучения (обратная связь в Learning Engine).
_VALIDATION_TO_EVENT: dict[str, str] = {
    "success": "success",
    "failure": "failure",
    "inconclusive": "insight",
}

# Базовый impact по приоритету улучшения-источника.
_PRIORITY_IMPACT: dict[str, float] = {
    "critical": 90.0,
    "high": 70.0,
    "medium": 50.0,
    "low": 30.0,
}


class AIOptimizationEngineError(Exception):
    """Ошибка Optimization Engine (нет проекта/оптимизации/эксперимента) — API → 400/404."""


class AIOptimizationEngineService:
    """AI-движок: improvement → score → experiment → measurement → validation → learning."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Цикл оптимизации (анализ)                                           #
    # ------------------------------------------------------------------ #

    def run_optimization_cycle(
        self, db: Session, project_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Оценить Improvement Backlog → оптимизации → приоритизация. НЕ применяет."""
        self._require_project(db, project_id)
        try:
            backlog = ci_repo.list_improvements(db, project_id)
        except Exception as exc:  # noqa: BLE001 — падение backlog не должно ронять цикл
            logger.warning("optimization backlog read failed: %s", type(exc).__name__)
            backlog = []
        improvements = [i for i in backlog if i.status in ("identified", "reviewed", "accepted")]
        created: list[dict[str, Any]] = []
        for improvement in improvements:
            view = self.create_optimization(db, project_id, improvement, user_id)
            if view is not None:
                created.append(view)
        ranked = self.prioritize_improvements(db, project_id, user_id)
        return {
            "created": created,
            "optimizations": ranked,
            "summary": repo.build_optimization_summary(db, project_id),
            "insights": self.explain_optimization(db, project_id)["insights"],
        }

    def create_optimization(
        self,
        db: Session,
        project_id: int,
        improvement: ImprovementItem,
        user_id: int | None = None,
    ) -> dict[str, Any] | None:
        """Создать OptimizationItem из ImprovementItem (идемпотентно). Оценивает score/priority."""
        existing = repo.list_optimizations_by_improvement(db, project_id, improvement.id)
        if existing:
            return None  # уже оценено — не дублируем
        account_id = self._account_id(db, project_id)
        impact = self._derive_impact(db, project_id, improvement)
        confidence = self._derive_confidence(db, improvement)
        cost = self._derive_cost(improvement)
        risk = self._derive_risk(db, project_id, improvement)
        score = self.calculate_optimization_score(impact, confidence, cost, risk)
        priority = self._priority_from_score(score)
        optimization = repo.create_optimization(
            db,
            project_id=project_id,
            account_id=account_id,
            improvement_id=improvement.id,
            title=improvement.title,
            description=improvement.description,
            impact_score=impact,
            confidence_score=confidence,
            cost_score=cost,
            risk_score=risk,
            optimization_score=score,
            priority=priority,
            status="identified",
        )
        self._write_audit(
            db,
            audit_actions.ACTION_OPTIMIZATION_CREATED,
            project_id,
            user_id,
            optimization.id,
            {"optimization_score": score, "priority": priority},
            entity_type="optimization_item",
        )
        return repo.public_optimization_view(optimization)

    def calculate_optimization_score(
        self, impact_score: float, confidence_score: float, cost_score: float, risk_score: float
    ) -> float:
        """Score = impact × confidence − cost − risk → 0..100.

        confidence берётся как доля (÷100), чтобы произведение осталось в шкале 0..100.
        """
        raw = (
            float(impact_score or 0.0) * (float(confidence_score or 0.0) / 100.0)
            - float(cost_score or 0.0)
            - float(risk_score or 0.0)
        )
        return round(self._clamp(raw, 0.0, 100.0), 1)

    def prioritize_improvements(
        self, db: Session, project_id: int, user_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Переоценить приоритет по score, вернуть ранжирование (critical→low). НЕ применяет."""
        optimizations = repo.list_optimizations(db, project_id)
        for optimization in optimizations:
            new_priority = self._priority_from_score(optimization.optimization_score)
            if new_priority != optimization.priority:
                repo.update_optimization(db, optimization, priority=new_priority)
        ranked = repo.sort_by_priority(optimizations)
        if optimizations:
            self._write_audit(
                db,
                audit_actions.ACTION_OPTIMIZATION_PRIORITIZED,
                project_id,
                user_id,
                None,
                {"ranked": len(ranked)},
                entity_type="optimization_item",
            )
        return [repo.public_optimization_view(o) for o in ranked]

    # ------------------------------------------------------------------ #
    # Эксперименты                                                       #
    # ------------------------------------------------------------------ #

    def create_experiment(
        self,
        db: Session,
        optimization_id: int,
        user_id: int | None = None,
        *,
        title: str | None = None,
        hypothesis: str | None = None,
        metric: str | None = None,
        baseline_value: float | None = None,
        target_value: float | None = None,
        measurement_period: int = 7,
    ) -> dict[str, Any]:
        """Создать эксперимент-гипотезу (status=draft — НЕ запускается автоматически)."""
        optimization = self._require_optimization(db, optimization_id)
        resolved_metric = (
            metric or self._infer_metric(optimization)
        ).strip() or "performance_score"
        resolved_hypothesis = hypothesis or self._build_hypothesis(optimization, resolved_metric)
        baseline = (
            float(baseline_value)
            if baseline_value is not None
            else self._baseline_for_metric(db, optimization)
        )
        target = (
            float(target_value)
            if target_value is not None
            else self._target_from_baseline(baseline)
        )
        experiment = repo.create_experiment(
            db,
            optimization_id=optimization_id,
            title=title or f"Эксперимент: {optimization.title}",
            hypothesis=resolved_hypothesis,
            metric=resolved_metric,
            baseline_value=baseline,
            target_value=target,
            status="draft",
            measurement_period=max(1, int(measurement_period or 7)),
        )
        # Оптимизация переходит в planned (эксперимент запланирован, НЕ запущен).
        # Терминальные статусы (completed/cancelled) НЕ регрессируем.
        if optimization.status not in ("completed", "cancelled"):
            repo.update_optimization(db, optimization, status="planned")
        self._write_audit(
            db,
            audit_actions.ACTION_OPTIMIZATION_EXPERIMENT_CREATED,
            optimization.project_id,
            user_id,
            experiment.id,
            {"metric": resolved_metric},
            entity_type="optimization_experiment",
        )
        return repo.public_experiment_view(experiment)

    def evaluate_experiment(
        self, experiment: OptimizationExperiment, actual_value: float
    ) -> dict[str, Any]:
        """Сравнить факт с ожиданием (target) и базой (baseline). Чистая функция."""
        baseline = float(experiment.baseline_value or 0.0)
        expected = float(experiment.target_value or 0.0)
        actual = float(actual_value or 0.0)
        difference = round(actual - expected, 2)
        return {
            "expected": expected,
            "actual": actual,
            "difference": difference,
            "analysis": {
                "metric": experiment.metric,
                "baseline": baseline,
                "target": expected,
                "actual": actual,
                "vs_target": difference,
                "vs_baseline": round(actual - baseline, 2),
            },
        }

    def validate_result(self, experiment: OptimizationExperiment, actual_value: float) -> str:
        """Определить итог: success / failure / inconclusive (с учётом направления метрики)."""
        baseline = float(experiment.baseline_value or 0.0)
        target = float(experiment.target_value or 0.0)
        actual = float(actual_value or 0.0)
        if target == baseline:
            return "inconclusive"
        if target > baseline:  # выше = лучше
            if actual >= target:
                return "success"
            if actual <= baseline:
                return "failure"
            return "inconclusive"
        # ниже = лучше (напр. число зависимостей)
        if actual <= target:
            return "success"
        if actual >= baseline:
            return "failure"
        return "inconclusive"

    def validate_experiment(
        self,
        db: Session,
        experiment_id: int,
        actual_value: float,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Завершить эксперимент: замер → валидация → результат → feedback. НЕ применяет."""
        experiment = self._require_experiment(db, experiment_id)
        if experiment.status == "completed":
            raise AIOptimizationEngineError("Эксперимент уже завершён")
        evaluation = self.evaluate_experiment(experiment, actual_value)
        validation = self.validate_result(experiment, actual_value)
        result = repo.create_result(
            db,
            experiment_id=experiment.id,
            actual_value=float(actual_value or 0.0),
            expected_value=evaluation["expected"],
            difference=evaluation["difference"],
            validation_result=validation,
            analysis=evaluation["analysis"],
        )
        repo.update_experiment(db, experiment, status="completed")
        self._write_audit(
            db,
            audit_actions.ACTION_OPTIMIZATION_EXPERIMENT_COMPLETED,
            self._experiment_project_id(db, experiment),
            user_id,
            experiment.id,
            {"validation_result": validation},
            entity_type="optimization_experiment",
        )
        optimization = repo.get_optimization(db, experiment.optimization_id)
        if optimization is not None:
            repo.update_optimization(db, optimization, status="completed")
        feedback = self.create_learning_feedback(db, experiment, result, optimization)
        self._write_audit(
            db,
            audit_actions.ACTION_OPTIMIZATION_EXPERIMENT_VALIDATED,
            self._experiment_project_id(db, experiment),
            user_id,
            experiment.id,
            {"validation_result": validation},
            entity_type="optimization_experiment",
        )
        return {
            "experiment": repo.public_experiment_view(experiment),
            "result": repo.public_result_view(result),
            "validation": validation,
            "learning_feedback": feedback,
        }

    def create_learning_feedback(
        self,
        db: Session,
        experiment: OptimizationExperiment,
        result: Any,
        optimization: OptimizationItem | None,
    ) -> dict[str, Any] | None:
        """Вернуть результат в Learning Engine: создать LearningEvent. НЕ меняет бизнес."""
        if optimization is None:
            return None
        project_id = optimization.project_id
        account_id = self._account_id(db, project_id)
        event_type = _VALIDATION_TO_EVENT.get(result.validation_result, "insight")
        try:
            event = ci_repo.create_event(
                db,
                project_id=project_id,
                account_id=account_id,
                event_type=event_type,
                title=f"Оптимизация: {experiment.title}"[:255],
                description=f"Эксперимент «{experiment.metric}» → {result.validation_result}",
                impact={
                    "metric": experiment.metric,
                    "difference": result.difference,
                    "validation": result.validation_result,
                },
            )
        except Exception as exc:  # noqa: BLE001 — обратная связь не должна ронять валидацию
            logger.warning("optimization learning feedback failed: %s", type(exc).__name__)
            return None
        return ci_repo.public_event_view(event)

    def explain_optimization(self, db: Session, project_id: int) -> dict[str, Any]:
        """Объяснить владельцу, почему улучшение выбрано первым."""
        summary = repo.build_optimization_summary(db, project_id)
        ranked = repo.sort_by_priority(repo.list_optimizations(db, project_id))
        insights: list[str] = [
            f"Оценено оптимизаций: {summary['optimizations_total']}, "
            f"экспериментов: {summary['experiments_total']}; "
            f"средний score {summary['avg_optimization_score']}."
        ]
        if ranked:
            top = ranked[0]
            sc = round(float(top.optimization_score or 0.0), 1)
            im = round(float(top.impact_score or 0.0), 1)
            cf = round(float(top.confidence_score or 0.0), 1)
            co = round(float(top.cost_score or 0.0), 1)
            rk = round(float(top.risk_score or 0.0), 1)
            insights.append(
                f"Первым выбрано «{top.title}»: score {sc} "
                f"(impact {im} × conf {cf} − cost {co} − risk {rk}), приоритет {top.priority}."
            )
        else:
            insights.append(
                "Пока нет оценённых улучшений — запустите анализ после появления backlog."
            )
        insights.append(
            "Это оценка и приоритизация; улучшения НЕ применяются, бизнес/KPI не меняются."
        )
        return {"project_id": project_id, "insights": insights}

    # ------------------------------------------------------------------ #
    # Чтение                                                             #
    # ------------------------------------------------------------------ #

    def get_optimizations(
        self, db: Session, project_id: int, status: str | None = None
    ) -> list[dict[str, Any]]:
        """Ранжированный список оптимизаций проекта."""
        self._require_project(db, project_id)
        return [
            repo.public_optimization_view(o)
            for o in repo.list_optimizations(db, project_id, status=status)
        ]

    def get_optimization_detail(self, db: Session, optimization_id: int) -> dict[str, Any]:
        """Оптимизация + её эксперименты."""
        optimization = self._require_optimization(db, optimization_id)
        return {
            "optimization": repo.public_optimization_view(optimization),
            "experiments": [
                repo.public_experiment_view(e) for e in repo.list_experiments(db, optimization.id)
            ],
        }

    def get_experiment_detail(self, db: Session, experiment_id: int) -> dict[str, Any]:
        """Эксперимент + его результаты."""
        experiment = self._require_experiment(db, experiment_id)
        return {
            "experiment": repo.public_experiment_view(experiment),
            "results": [repo.public_result_view(r) for r in repo.list_results(db, experiment.id)],
        }

    # ------------------------------------------------------------------ #
    # Деривация оценок (read-only смежные слои)                          #
    # ------------------------------------------------------------------ #

    def _derive_impact(self, db: Session, project_id: int, improvement: ImprovementItem) -> float:
        """Impact по приоритету улучшения + буст за значимые отклонения (Performance, read-only)."""
        base = _PRIORITY_IMPACT.get(improvement.priority, 50.0)
        try:
            from app.repositories import performance_repository as perf_repo

            snapshot = perf_repo.get_latest_snapshot(db, project_id)
            if snapshot is not None:
                severe = [
                    d
                    for d in perf_repo.list_deviations(db, snapshot.id)
                    if d.impact in ("high", "critical")
                ]
                if severe:
                    base += 10.0
        except Exception as exc:  # noqa: BLE001
            logger.warning("optimization impact performance failed: %s", type(exc).__name__)
        return self._clamp(base, 0.0, 100.0)

    def _derive_confidence(self, db: Session, improvement: ImprovementItem) -> float:
        """Confidence из паттерна-источника улучшения (AIPattern, read-only), иначе средняя."""
        try:
            if improvement.pattern_id:
                pattern = ci_repo.get_pattern(db, improvement.pattern_id)
                if pattern is not None:
                    return self._clamp(float(pattern.confidence_score or 0.0), 0.0, 100.0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("optimization confidence pattern failed: %s", type(exc).__name__)
        return 50.0

    @staticmethod
    def _derive_cost(improvement: ImprovementItem) -> float:
        """Стоимость изменения (эвристика; штраф скромный, чтобы score не занулялся)."""
        text = f"{improvement.title or ''} {improvement.description or ''}".lower()
        if "стратег" in text or "пересмотр" in text:
            return 40.0  # смена стратегии — дорого
        if "данн" in text or "прогноз" in text:
            return 25.0
        if "владельц" in text or "назначить" in text:
            return 10.0  # назначить владельца — дёшево
        return 20.0

    def _derive_risk(self, db: Session, project_id: int, improvement: ImprovementItem) -> float:
        """Риск: база + заблокированные задачи исполнения (Execution, read-only)."""
        base = 10.0
        try:
            from app.repositories import execution_repository as exec_repo

            plans = exec_repo.list_execution_plans(db, project_id, limit=1)
            if plans:
                blocked = exec_repo.get_blocked_tasks(db, plans[0].id)
                base += min(20.0, len(blocked) * 5.0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("optimization risk execution failed: %s", type(exc).__name__)
        return self._clamp(base, 0.0, 100.0)

    @staticmethod
    def _infer_metric(optimization: OptimizationItem) -> str:
        """Метрика проверки по смыслу оптимизации."""
        text = f"{optimization.title or ''} {optimization.description or ''}".lower()
        if "зависимост" in text or "блокер" in text or "исполнен" in text or "ресурс" in text:
            return "execution_speed"
        if "прогноз" in text:
            return "forecast_accuracy"
        if "стратег" in text or "конверси" in text:
            return "conversion"
        return "performance_score"

    @staticmethod
    def _build_hypothesis(optimization: OptimizationItem, metric: str) -> str:
        return f"«{optimization.title}» улучшит метрику {metric}"

    def _baseline_for_metric(self, db: Session, optimization: OptimizationItem) -> float:
        """База измерения — текущий Performance Score проекта (read-only), иначе 50."""
        try:
            from app.repositories import performance_repository as perf_repo

            snapshot = perf_repo.get_latest_snapshot(db, optimization.project_id)
            if snapshot is not None:
                return round(float(snapshot.performance_score or 0.0), 2)
        except Exception as exc:  # noqa: BLE001
            logger.warning("optimization baseline performance failed: %s", type(exc).__name__)
        return 50.0

    @staticmethod
    def _target_from_baseline(baseline: float) -> float:
        """Цель = +15% к базе (или 60, если база нулевая), не выше 100."""
        if baseline <= 0:
            return 60.0
        return round(min(100.0, baseline * 1.15), 2)

    # ------------------------------------------------------------------ #
    # Внутреннее                                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _priority_from_score(score: float) -> str:
        value = float(score or 0.0)
        if value >= 75.0:
            return "critical"
        if value >= 50.0:
            return "high"
        if value >= 25.0:
            return "medium"
        return "low"

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, float(value)))

    def _require_project(self, db: Session, project_id: int) -> Any:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise AIOptimizationEngineError(f"Проект id={project_id} не найден")
        return project

    def _require_optimization(self, db: Session, optimization_id: int) -> OptimizationItem:
        optimization = repo.get_optimization(db, optimization_id)
        if optimization is None:
            raise AIOptimizationEngineError("Оптимизация не найдена")
        return optimization

    def _require_experiment(self, db: Session, experiment_id: int) -> OptimizationExperiment:
        experiment = repo.get_experiment(db, experiment_id)
        if experiment is None:
            raise AIOptimizationEngineError("Эксперимент не найден")
        return experiment

    def _experiment_project_id(self, db: Session, experiment: OptimizationExperiment) -> int:
        """project_id эксперимента через его оптимизацию (для audit/tenant)."""
        optimization = repo.get_optimization(db, experiment.optimization_id)
        return optimization.project_id if optimization is not None else 0

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
        entity_type: str = "optimization_item",
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


def get_ai_optimization_engine_service() -> AIOptimizationEngineService:
    """DI-фабрика AI Autonomous Optimization."""
    return AIOptimizationEngineService()
