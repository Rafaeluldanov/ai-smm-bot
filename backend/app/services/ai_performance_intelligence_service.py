"""AIPerformanceIntelligenceService — AI Performance Intelligence Engine (v0.7.9).

Измеряет эффективность исполнения бизнес-плана: собирает фактические результаты (Execution
Coordinator / Business Growth profile / Operations — только READ-ONLY чтение персистов), сравнивает
с планом (Business Planner / Forecasting), считает performance score, находит отклонения, определяет
причины и советует улучшения.

Поток: **Execution Plan → Performance Snapshot → Actual vs Target → Deviation Analysis →
Recommendations**.

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- это аналитический слой: только измеряет и советует;
- НЕ меняет планы/KPI, НЕ меняет бизнес/CRM/бюджет, НЕ выполняет задачи и рекомендации, НЕ
  запускает рекламу, НЕ публикует, НЕ ходит во внешние действия;
- строго per-project; секретов нет; бесплатно (0 units);
- каждое изменение (snapshot_created/metric_created/deviation_detected/recommendation_created)
  пишется в AuditLog.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import performance_repository as repo
from app.repositories import project_repository
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.performance_snapshot import PerformanceSnapshot
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

# KPI-метрики (участвуют в kpi_score и сравнении план/факт).
_KPI_METRICS: tuple[str, ...] = ("revenue", "sales", "leads", "conversion")
# Все метрики снимка (порядок вывода).
_ALL_METRICS: tuple[str, ...] = (
    "revenue",
    "sales",
    "leads",
    "conversion",
    "execution",
    "efficiency",
)

# Тип бизнес-цели (Business Planner) → метрика эффективности (для целей).
_GOAL_TO_METRIC: dict[str, str] = {
    "revenue": "revenue",
    "sales": "sales",
    "leads": "leads",
    "marketing": "leads",
    "growth": "efficiency",
    "efficiency": "efficiency",
    "operational": "execution",
}

# Порог отклонения (difference_percent) → статус метрики.
_WARN_THRESHOLD = -5.0
_CRIT_THRESHOLD = -25.0


class AIPerformanceIntelligenceError(Exception):
    """Ошибка Performance Intelligence (нет проекта/снимка) — API → 400/404."""


class AIPerformanceIntelligenceService:
    """AI-движок эффективности: snapshot → actual vs target → deviations → recommendations."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Анализ (создание снимка)                                            #
    # ------------------------------------------------------------------ #

    def create_snapshot(
        self, db: Session, project_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Собрать снимок эффективности: факт vs план → score → отклонения → рекомендации.

        НЕ меняет планы/KPI/бизнес. Только измеряет и советует.
        """
        self._require_project(db, project_id)
        execution_plan_id = self._latest_execution_plan_id(db, project_id)

        actual = self.collect_actual_metrics(db, project_id, execution_plan_id)
        target = self.collect_target_metrics(db, project_id)
        comparison = self.compare_metrics(actual, target)
        score = self.calculate_performance_score(db, project_id, actual, comparison)
        status = self._status_from_score(score)

        snapshot = repo.create_snapshot(
            db,
            project_id=project_id,
            account_id=self._account_id(db, project_id),
            execution_plan_id=execution_plan_id,
            status=status,
            performance_score=score,
            metrics={"comparison": comparison},
            target_state=target,
            actual_state=actual,
        )
        self._write_audit(
            db,
            audit_actions.ACTION_PERFORMANCE_SNAPSHOT_CREATED,
            project_id,
            user_id,
            snapshot.id,
            {"score": score, "status": status},
        )

        self._persist_metrics(db, snapshot, comparison, project_id, user_id)
        root_causes = self.analyze_root_causes(db, project_id, comparison)
        self.detect_deviations(db, snapshot, comparison, root_causes, project_id, user_id)
        self.generate_recommendations(db, snapshot, comparison, project_id, user_id)
        return self.get_snapshot(db, snapshot.id)

    # ------------------------------------------------------------------ #
    # Сбор факта / плана                                                 #
    # ------------------------------------------------------------------ #

    def collect_actual_metrics(
        self, db: Session, project_id: int, execution_plan_id: int | None
    ) -> dict[str, float]:
        """Собрать фактические метрики (revenue/sales/leads/conversion/execution/efficiency)."""
        actual: dict[str, float] = dict.fromkeys(_ALL_METRICS, 0.0)

        # Business Growth profile (ПЕРСИСТ, READ-ONLY): revenue/leads/conversion/growth_score.
        # ВАЖНО: НЕ вызываем analyze_business_state — это WRITE-путь (создаёт/меняет профиль роста
        # и пишет growth.analyzed). Аналитика обязана только читать → get_profile (чистый SELECT).
        try:
            from app.repositories import business_growth_repository as growth_repo

            profile = growth_repo.get_profile(db, project_id)
            if profile is not None:
                cs = profile.current_state or {}
                actual["revenue"] = float(cs.get("total_revenue", 0.0) or 0.0)
                actual["leads"] = float(cs.get("leads", 0) or 0)
                actual["conversion"] = float(cs.get("conversion_rate", 0.0) or 0.0)
                actual["sales"] = round(actual["leads"] * actual["conversion"], 2)
                actual["efficiency"] = float(profile.growth_score or 0.0)
        except Exception as exc:  # noqa: BLE001 — нижний слой не должен ронять сбор факта
            logger.warning("performance growth actual failed: %s", type(exc).__name__)

        # Execution Coordinator: прогресс исполнения (execution).
        if execution_plan_id is not None:
            try:
                from app.repositories import execution_repository as exec_repo

                actual["execution"] = float(exec_repo.calculate_progress(db, execution_plan_id))
            except Exception as exc:  # noqa: BLE001
                logger.warning("performance execution actual failed: %s", type(exc).__name__)

        # Operations: health-score как запасной сигнал эффективности.
        try:
            from app.repositories import operations_repository as ops_repo

            snapshot = ops_repo.get_latest_snapshot(db, project_id)
            if snapshot is not None and not actual["efficiency"]:
                actual["efficiency"] = float(snapshot.health_score or 0.0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("performance operations actual failed: %s", type(exc).__name__)

        return {k: round(v, 2) for k, v in actual.items()}

    def collect_target_metrics(self, db: Session, project_id: int) -> dict[str, float]:
        """Собрать плановые метрики (Business Planner KPI / Execution Objectives / Forecast)."""
        target: dict[str, float] = dict.fromkeys(_ALL_METRICS, 0.0)
        target["execution"] = 100.0  # цель исполнения — полное завершение
        target["efficiency"] = 100.0  # цель эффективности — максимум

        # Business Planner: цели владельца (goal_type → метрика, target_value).
        try:
            from app.repositories import business_planner_repository as planner_repo

            for goal in planner_repo.list_goals(db, project_id):
                metric = _GOAL_TO_METRIC.get(goal.goal_type)
                value = float(goal.target_value or 0.0)
                if metric and value > 0 and value > target.get(metric, 0.0):
                    target[metric] = value
        except Exception as exc:  # noqa: BLE001
            logger.warning("performance planner target failed: %s", type(exc).__name__)

        # Business Forecasting: прогнозные ориентиры (baseline+ожидаемое изменение по выручке).
        try:
            from app.repositories import business_forecast_repository as fc_repo

            forecast = fc_repo.get_latest_forecast(db, project_id)
            if forecast is not None and not target["revenue"]:
                baseline = float((forecast.baseline_state or {}).get("revenue", 0.0) or 0.0)
                block = (forecast.forecast_state or {}).get("12_months", {}) or {}
                change = float(block.get("revenue", 0.0) or 0.0)
                if baseline > 0:
                    target["revenue"] = round(baseline * (1 + change / 100.0), 2)
        except Exception as exc:  # noqa: BLE001
            logger.warning("performance forecast target failed: %s", type(exc).__name__)

        return {k: round(v, 2) for k, v in target.items()}

    def compare_metrics(
        self, actual: dict[str, float], target: dict[str, float]
    ) -> list[dict[str, Any]]:
        """Сравнить факт vs план по каждой метрике: difference, difference_percent, status."""
        comparison: list[dict[str, Any]] = []
        for metric in _ALL_METRICS:
            target_value = float(target.get(metric, 0.0) or 0.0)
            actual_value = float(actual.get(metric, 0.0) or 0.0)
            if target_value <= 0:
                continue  # без плана метрику не оцениваем
            difference = round(actual_value - target_value, 2)
            difference_percent = round(difference / target_value * 100.0, 1)
            comparison.append(
                {
                    "metric": metric,
                    "target_value": round(target_value, 2),
                    "actual_value": round(actual_value, 2),
                    "difference": difference,
                    "difference_percent": difference_percent,
                    "status": self._metric_status(difference_percent),
                }
            )
        return comparison

    # ------------------------------------------------------------------ #
    # Score / отклонения / причины / рекомендации                        #
    # ------------------------------------------------------------------ #

    def calculate_performance_score(
        self,
        db: Session,
        project_id: int,
        actual: dict[str, float],
        comparison: list[dict[str, Any]],
    ) -> float:
        """Performance Score = execution + kpi + velocity − risk_penalty, clamp [0..100]."""
        execution_score = (
            self._clamp(float(actual.get("execution", 0.0)), 0.0, 100.0) / 100.0 * 40.0
        )

        kpi_items = [c for c in comparison if c["metric"] in _KPI_METRICS]
        if kpi_items:
            ratios = [
                self._clamp(c["actual_value"] / c["target_value"], 0.0, 1.0)
                for c in kpi_items
                if c["target_value"] > 0
            ]
            kpi_score = (sum(ratios) / len(ratios)) * 40.0 if ratios else 0.0
        else:
            kpi_score = 0.0

        velocity_score = self._velocity_score(db, project_id)
        risk_penalty = self._risk_penalty(db, project_id)

        raw = execution_score + kpi_score + velocity_score - risk_penalty
        return round(self._clamp(raw, 0.0, 100.0), 1)

    def detect_deviations(
        self,
        db: Session,
        snapshot: PerformanceSnapshot,
        comparison: list[dict[str, Any]],
        root_causes: list[str],
        project_id: int,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Создать отклонения по метрикам со статусом warning/critical (недовыполнение)."""
        created: list[dict[str, Any]] = []
        for c in comparison:
            if c["status"] == "healthy":
                continue
            dp = float(c["difference_percent"])
            impact = self._impact_from_deviation(dp)
            metric = c["metric"]
            deviation = repo.create_deviation(
                db,
                snapshot_id=snapshot.id,
                metric=metric,
                title=f"Отклонение по «{metric}»: {dp:+.1f}%",
                deviation_type="negative" if dp < 0 else "positive",
                impact=impact,
                description=(
                    f"Факт {c['actual_value']} против плана {c['target_value']} "
                    f"(разница {c['difference']})."
                ),
                root_causes=self._metric_root_causes(metric, root_causes),
            )
            created.append(repo.public_deviation_view(deviation))
        if created:
            self._write_audit(
                db,
                audit_actions.ACTION_PERFORMANCE_DEVIATION_DETECTED,
                project_id,
                user_id,
                snapshot.id,
                {"deviations": len(created)},
            )
        return created

    def analyze_root_causes(
        self, db: Session, project_id: int, comparison: list[dict[str, Any]]
    ) -> list[str]:
        """Определить вероятные причины отклонений (Execution/Operations/метрики). Только чтение."""
        causes: list[str] = []
        # Метрические причины.
        by_metric = {c["metric"]: c for c in comparison}
        if by_metric.get("leads", {}).get("status", "healthy") != "healthy":
            causes.append("нет лидов / слабый входящий поток")
        if by_metric.get("conversion", {}).get("status", "healthy") != "healthy":
            causes.append("низкая конверсия")
        # Execution: заблокированные/незавершённые задачи.
        try:
            from app.repositories import execution_repository as exec_repo

            plan_id = self._latest_execution_plan_id(db, project_id)
            if plan_id is not None:
                blocked = exec_repo.get_blocked_tasks(db, plan_id)
                tasks = exec_repo.list_tasks_for_plan(db, plan_id)
                incomplete = sum(1 for t in tasks if t.status not in ("completed", "cancelled"))
                if blocked:
                    causes.append(f"блокеры в исполнении ({len(blocked)})")
                if incomplete and not blocked:
                    causes.append("задержка задач исполнения")
        except Exception as exc:  # noqa: BLE001
            logger.warning("performance execution cause failed: %s", type(exc).__name__)
        # Operations: открытые риски.
        try:
            from app.repositories import operations_repository as ops_repo

            risks = ops_repo.list_active_risks(db, project_id)
            if risks:
                causes.append(f"открытые операционные риски ({len(risks)})")
        except Exception as exc:  # noqa: BLE001
            logger.warning("performance operations cause failed: %s", type(exc).__name__)
        return causes

    def generate_recommendations(
        self,
        db: Session,
        snapshot: PerformanceSnapshot,
        comparison: list[dict[str, Any]],
        project_id: int,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Создать рекомендации по отклонениям (только советы, НЕ выполняются)."""
        created: list[dict[str, Any]] = []
        for c in comparison:
            if c["status"] == "healthy":
                continue
            title = _METRIC_ADVICE.get(c["metric"], f"Улучшить показатель «{c['metric']}».")
            recommendation = repo.create_recommendation(
                db,
                snapshot_id=snapshot.id,
                title=title,
                priority=self._impact_from_deviation(float(c["difference_percent"])),
                description=(
                    f"Метрика «{c['metric']}» ниже плана на "
                    f"{abs(float(c['difference_percent']))}% — рекомендация к улучшению."
                ),
                expected_effect={"metric": c["metric"], "gap_percent": c["difference_percent"]},
            )
            created.append(repo.public_recommendation_view(recommendation))
        if not created:
            recommendation = repo.create_recommendation(
                db,
                snapshot_id=snapshot.id,
                title="Удерживать текущий темп — план выполняется.",
                priority="low",
                expected_effect={},
            )
            created.append(repo.public_recommendation_view(recommendation))
        self._write_audit(
            db,
            audit_actions.ACTION_PERFORMANCE_RECOMMENDATION_CREATED,
            project_id,
            user_id,
            snapshot.id,
            {"recommendations": len(created)},
        )
        return created

    def explain_performance(self, db: Session, snapshot_id: int) -> dict[str, Any]:
        """Объяснить владельцу: почему такой Performance Score."""
        snapshot = self._require_snapshot(db, snapshot_id)
        comparison = (snapshot.metrics or {}).get("comparison", [])
        reasons: list[str] = [
            f"Performance Score {round(float(snapshot.performance_score or 0.0), 1)}/100 "
            f"(статус: {snapshot.status}).",
            "Score = исполнение + достижение KPI + скорость − штраф за риски.",
        ]
        for c in comparison:
            if c.get("status") != "healthy":
                reasons.append(
                    f"«{c['metric']}»: факт {c['actual_value']} vs план {c['target_value']} "
                    f"({c['difference_percent']:+.1f}%)."
                )
        if len(reasons) == 2:
            reasons.append("Ключевые метрики в пределах плана.")
        reasons.append("Это измерение и рекомендации; планы/бизнес не меняются.")
        return {"snapshot_id": snapshot_id, "reasons": reasons}

    # ------------------------------------------------------------------ #
    # Чтение                                                             #
    # ------------------------------------------------------------------ #

    def list_snapshots(
        self, db: Session, project_id: int, status: str | None = None
    ) -> dict[str, Any]:
        """Список снимков проекта + сводка."""
        self._require_project(db, project_id)
        return {
            "snapshots": [
                repo.public_snapshot_view(s)
                for s in repo.list_snapshots(db, project_id, status=status)
            ],
            "summary": repo.build_performance_summary(db, project_id),
        }

    def get_snapshot(self, db: Session, snapshot_id: int) -> dict[str, Any]:
        """Снимок + метрики + отклонения + рекомендации."""
        snapshot = self._require_snapshot(db, snapshot_id)
        return {
            "snapshot": repo.public_snapshot_view(snapshot),
            "metrics": [repo.public_metric_view(m) for m in repo.list_metrics(db, snapshot_id)],
            "deviations": [
                repo.public_deviation_view(d) for d in repo.list_deviations(db, snapshot_id)
            ],
            "recommendations": [
                repo.public_recommendation_view(r)
                for r in repo.list_recommendations(db, snapshot_id)
            ],
        }

    def get_metrics(self, db: Session, snapshot_id: int) -> list[dict[str, Any]]:
        """Метрики снимка."""
        self._require_snapshot(db, snapshot_id)
        return [repo.public_metric_view(m) for m in repo.list_metrics(db, snapshot_id)]

    def get_deviations(self, db: Session, snapshot_id: int) -> list[dict[str, Any]]:
        """Отклонения снимка."""
        self._require_snapshot(db, snapshot_id)
        return [repo.public_deviation_view(d) for d in repo.list_deviations(db, snapshot_id)]

    def get_recommendations(self, db: Session, snapshot_id: int) -> list[dict[str, Any]]:
        """Рекомендации снимка + объяснение."""
        self._require_snapshot(db, snapshot_id)
        return [
            repo.public_recommendation_view(r) for r in repo.list_recommendations(db, snapshot_id)
        ]

    # ------------------------------------------------------------------ #
    # Внутреннее                                                         #
    # ------------------------------------------------------------------ #

    def _persist_metrics(
        self,
        db: Session,
        snapshot: PerformanceSnapshot,
        comparison: list[dict[str, Any]],
        project_id: int,
        user_id: int | None,
    ) -> None:
        for c in comparison:
            repo.create_metric(
                db,
                snapshot_id=snapshot.id,
                metric=c["metric"],
                target_value=c["target_value"],
                actual_value=c["actual_value"],
                difference=c["difference"],
                difference_percent=c["difference_percent"],
                status=c["status"],
                reasoning=[
                    f"Факт {c['actual_value']} vs план {c['target_value']} "
                    f"({c['difference_percent']:+.1f}%)."
                ],
            )
        if comparison:
            self._write_audit(
                db,
                audit_actions.ACTION_PERFORMANCE_METRIC_CREATED,
                project_id,
                user_id,
                snapshot.id,
                {"metrics": len(comparison)},
            )

    def _velocity_score(self, db: Session, project_id: int) -> float:
        """Скорость исполнения (0..20): доля завершённых задач последнего плана исполнения."""
        try:
            from app.repositories import execution_repository as exec_repo

            plan_id = self._latest_execution_plan_id(db, project_id)
            if plan_id is None:
                return 0.0
            tasks = exec_repo.list_tasks_for_plan(db, plan_id)
            active = [t for t in tasks if t.status != "cancelled"]
            if not active:
                return 0.0
            completed = sum(1 for t in active if t.status == "completed")
            return round(completed / len(active) * 20.0, 1)
        except Exception as exc:  # noqa: BLE001
            logger.warning("performance velocity failed: %s", type(exc).__name__)
            return 0.0

    def _risk_penalty(self, db: Session, project_id: int) -> float:
        """Штраф за риски (0..20): открытые операционные риски + заблокированные задачи."""
        penalty = 0.0
        try:
            from app.repositories import operations_repository as ops_repo

            penalty += len(ops_repo.list_active_risks(db, project_id)) * 4.0
        except Exception as exc:  # noqa: BLE001
            logger.warning("performance risk penalty ops failed: %s", type(exc).__name__)
        try:
            from app.repositories import execution_repository as exec_repo

            plan_id = self._latest_execution_plan_id(db, project_id)
            if plan_id is not None:
                penalty += len(exec_repo.get_blocked_tasks(db, plan_id)) * 3.0
        except Exception as exc:  # noqa: BLE001
            logger.warning("performance risk penalty exec failed: %s", type(exc).__name__)
        return round(self._clamp(penalty, 0.0, 20.0), 1)

    def _latest_execution_plan_id(self, db: Session, project_id: int) -> int | None:
        try:
            from app.repositories import execution_repository as exec_repo

            plans = exec_repo.list_execution_plans(db, project_id, limit=1)
            return plans[0].id if plans else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("performance latest execution plan failed: %s", type(exc).__name__)
            return None

    @staticmethod
    def _metric_root_causes(metric: str, root_causes: list[str]) -> list[str]:
        """Отфильтровать общие причины под конкретную метрику (+общие исполнения/рисков)."""
        exec_markers = ("задач", "блокер", "риск")
        specific: list[str] = []
        for cause in root_causes:
            low = cause.lower()
            matched = (
                (metric == "leads" and "лид" in low)
                or (metric == "conversion" and "конвер" in low)
                or (
                    metric in ("execution", "revenue", "sales")
                    and any(marker in low for marker in exec_markers)
                )
            )
            if matched:
                specific.append(cause)
        return specific or root_causes

    @staticmethod
    def _metric_status(difference_percent: float) -> str:
        if difference_percent >= _WARN_THRESHOLD:
            return "healthy"
        if difference_percent >= _CRIT_THRESHOLD:
            return "warning"
        return "critical"

    @staticmethod
    def _impact_from_deviation(difference_percent: float) -> str:
        dp = abs(difference_percent)
        if dp < 15:
            return "low"
        if dp < 30:
            return "medium"
        if dp < 50:
            return "high"
        return "critical"

    @staticmethod
    def _status_from_score(score: float) -> str:
        if score >= 70:
            return "healthy"
        if score >= 40:
            return "warning"
        return "critical"

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, float(value)))

    def _require_project(self, db: Session, project_id: int) -> Any:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise AIPerformanceIntelligenceError(f"Проект id={project_id} не найден")
        return project

    def _require_snapshot(self, db: Session, snapshot_id: int) -> PerformanceSnapshot:
        snapshot = repo.get_snapshot(db, snapshot_id)
        if snapshot is None:
            raise AIPerformanceIntelligenceError("Снимок эффективности не найден")
        return snapshot

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
            entity_type="performance_snapshot",
            entity_id=entity_id,
            metadata=metadata,
        )


# Рекомендация по метрике (только совет).
_METRIC_ADVICE: dict[str, str] = {
    "revenue": "Сфокусироваться на продающем контенте и офферах.",
    "sales": "Усилить работу с лидами до сделки.",
    "leads": "Увеличить поток лидов из контента.",
    "conversion": "Улучшить конверсию (CTA, кейсы, доверие).",
    "execution": "Ускорить исполнение и снять блокеры задач.",
    "efficiency": "Повысить эффективность процессов и фокус.",
}


def get_ai_performance_intelligence_service() -> AIPerformanceIntelligenceService:
    """DI-фабрика AI Performance Intelligence."""
    return AIPerformanceIntelligenceService()
