"""AIStrategySimulatorService — AI Strategy Simulator (v0.7.5).

Берёт сценарий решения (Decision Engine), моделирует его последствия на горизонте 30/60/90 дней,
строит прогноз метрик, оценивает уверенность, сравнивает сценарии и рекомендует лучший.

Поток: **Decision Scenario → Simulation → Forecast → Comparison → Recommendation**.

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- это аналитический слой: только моделирует и советует;
- НЕ гарантирует прибыль/финансовый результат (прогноз — модельная оценка);
- НЕ меняет бизнес/CRM/бюджет/продажи, НЕ запускает рекламу, НЕ публикует, НЕ включает live;
- НЕ выполняет стратегии автоматически; строго per-project; секретов нет; бесплатно (0 units);
- каждое изменение (created/started/completed/compared/recommended) пишется в AuditLog.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import decision_repository as decision_repo
from app.repositories import project_repository
from app.repositories import strategy_simulation_repository as repo
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.decision_scenario import DecisionScenario
    from app.models.scenario_comparison import ScenarioComparison
    from app.models.strategy_simulation import StrategySimulation
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

# Горизонты симуляции (дни) — фиксированная траектория 30/60/90.
_HORIZON_DAYS: tuple[int, ...] = (30, 60, 90)
_DAYS_TO_PERIOD: dict[int, str] = {30: "30_days", 60: "60_days", 90: "90_days"}
_DAYS_TO_MONTHS: dict[int, float] = {30: 1.0, 60: 2.0, 90: 3.0}

# Метрики прогноза и их отзывчивость на воздействие (0..1): выручка/лиды двигаются сильнее,
# чем конверсия/эффективность.
_METRIC_RESPONSIVENESS: dict[str, float] = {
    "revenue": 1.0,
    "leads": 0.9,
    "traffic": 0.85,
    "engagement": 0.6,
    "conversion": 0.55,
    "efficiency": 0.5,
}
# Порядок метрик в прогнозе (первичные 4 из baseline + вовлечённость/эффективность).
_FORECAST_METRICS: tuple[str, ...] = (
    "revenue",
    "leads",
    "conversion",
    "traffic",
    "engagement",
    "efficiency",
)

# Максимальный месячный прирост при полном воздействии и нулевом риске (12%).
_MAX_MONTHLY_LIFT = 0.12
# Число источников baseline (для оценки полноты данных).
_BASELINE_SOURCES = 3


class AIStrategySimulatorError(Exception):
    """Ошибка Strategy Simulator (нет проекта/сценария/симуляции) — API → 400/404."""


class AIStrategySimulatorService:
    """AI-симулятор стратегии: scenario → simulation → forecast → comparison → recommendation."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Симуляции: создание / чтение                                       #
    # ------------------------------------------------------------------ #

    def create_simulation(
        self,
        db: Session,
        project_id: int,
        *,
        scenario_id: int,
        title: str | None = None,
        objective: str | None = None,
        simulation_period: str = "90_days",
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Создать симуляцию из сценария решения (Decision Engine). НЕ запускает моделирование."""
        from app.models.strategy_simulation import FORECAST_PERIODS

        self._require_project(db, project_id)
        scenario = self._require_scenario_in_project(db, scenario_id, project_id)
        if simulation_period not in FORECAST_PERIODS:
            raise AIStrategySimulatorError("Неизвестный горизонт прогноза")

        clean_title = (title or "").strip() or f"Симуляция: {scenario.title}"
        simulation = repo.create_simulation(
            db,
            project_id=project_id,
            account_id=self._account_id(db, project_id),
            scenario_id=scenario.id,
            decision_id=scenario.decision_id,
            title=clean_title,
            objective=objective,
            assumptions=list(scenario.assumptions or []),
            simulation_period=simulation_period,
            confidence_level="medium",
            status="generated",
        )
        self._write_audit(
            db,
            audit_actions.ACTION_SIMULATION_CREATED,
            project_id,
            user_id,
            simulation.id,
            {"scenario_id": scenario.id, "period": simulation_period},
        )
        return repo.public_simulation_view(simulation)

    def list_simulations(
        self, db: Session, project_id: int, status: str | None = None
    ) -> list[dict[str, Any]]:
        """Список симуляций проекта (по статусу)."""
        self._require_project(db, project_id)
        return [
            repo.public_simulation_view(s)
            for s in repo.list_simulations(db, project_id, status=status)
        ]

    def get_simulation(self, db: Session, simulation_id: int) -> dict[str, Any]:
        """Симуляция + прогнозы."""
        simulation = self._require_simulation(db, simulation_id)
        return {
            "simulation": repo.public_simulation_view(simulation),
            "forecast": [
                repo.public_forecast_view(f) for f in repo.list_forecasts(db, simulation_id)
            ],
        }

    def get_forecast(self, db: Session, simulation_id: int) -> list[dict[str, Any]]:
        """Прогнозы симуляции."""
        self._require_simulation(db, simulation_id)
        return [repo.public_forecast_view(f) for f in repo.list_forecasts(db, simulation_id)]

    def get_summary(self, db: Session, project_id: int) -> dict[str, Any]:
        """Сводка Strategy Simulator (для UI-состояния)."""
        self._require_project(db, project_id)
        return repo.build_simulation_summary(db, project_id)

    # ------------------------------------------------------------------ #
    # Baseline: текущее состояние метрик                                 #
    # ------------------------------------------------------------------ #

    def collect_baseline(self, db: Session, project_id: int) -> dict[str, Any]:
        """Собрать базовые метрики из смежных слоёв (Sales/Growth/Operations/Analytics).

        Возвращает {revenue, leads, conversion, traffic, engagement, efficiency} + метаданные
        полноты данных. Каждый источник в try/except — отсутствие слоя не роняет симуляцию.
        """
        baseline: dict[str, float] = dict.fromkeys(_FORECAST_METRICS, 0.0)
        sources_with_data = 0

        # Sales / Growth (executive state): revenue, leads, conversion, growth_score.
        try:
            from app.services.ai_executive_service import AIExecutiveService

            state = AIExecutiveService(settings=self._resolve_settings()).analyze_business_state(
                db, project_id
            )
            rev = state.get("revenue_state", {}) or {}
            sales = state.get("sales_state", {}) or {}
            baseline["revenue"] = float(rev.get("total_revenue", 0.0) or 0.0)
            baseline["leads"] = float(sales.get("leads", 0) or 0)
            baseline["conversion"] = float(rev.get("conversion_rate", 0.0) or 0.0)
            baseline["efficiency"] = float(state.get("growth_score", 0.0) or 0.0)
            if baseline["revenue"] or baseline["leads"] or baseline["efficiency"]:
                sources_with_data += 1
        except Exception as exc:  # noqa: BLE001 — нижний слой не должен ронять baseline
            logger.warning("simulator executive baseline failed: %s", type(exc).__name__)

        # Analytics: traffic (reach) + engagement.
        try:
            from app.services.analytics_service import AnalyticsService

            summary = AnalyticsService().get_project_summary(db, project_id)
            baseline["traffic"] = float(getattr(summary, "total_reach", 0) or 0)
            baseline["engagement"] = float(getattr(summary, "avg_engagement_rate", 0.0) or 0.0)
            if baseline["traffic"] or baseline["engagement"]:
                sources_with_data += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("simulator analytics baseline failed: %s", type(exc).__name__)

        # Operations Center: health-score как запасной сигнал эффективности + полнота данных.
        try:
            from app.repositories import operations_repository as ops_repo

            snapshot = ops_repo.get_latest_snapshot(db, project_id)
            if snapshot is not None:
                if not baseline["efficiency"]:
                    baseline["efficiency"] = float(snapshot.health_score or 0.0)
                sources_with_data += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("simulator operations baseline failed: %s", type(exc).__name__)

        return {
            **baseline,
            "_meta": {
                "sources_with_data": sources_with_data,
                "sources_total": _BASELINE_SOURCES,
            },
        }

    # ------------------------------------------------------------------ #
    # Симуляция: моделирование будущего                                  #
    # ------------------------------------------------------------------ #

    def simulate_scenario(
        self, db: Session, simulation_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Запустить моделирование: baseline → прогноз метрик на 30/60/90 дней → уверенность.

        НЕ гарантирует результат: forecast_value — модельная оценка. НЕ меняет бизнес/CRM/бюджет.
        """
        simulation = self._require_simulation(db, simulation_id)
        scenario = self._require_scenario(db, simulation.scenario_id)

        repo.update_simulation(db, simulation, status="running")
        self._write_audit(
            db,
            audit_actions.ACTION_SIMULATION_STARTED,
            simulation.project_id,
            user_id,
            simulation.id,
            {"scenario_id": scenario.id},
        )

        impact, confidence, risk = self._scenario_signals(scenario)
        baseline = self.collect_baseline(db, simulation.project_id)
        meta = baseline.get("_meta", {})
        base_conf = self.calculate_forecast_confidence(
            sources_with_data=int(meta.get("sources_with_data", 0)),
            sources_total=int(meta.get("sources_total", _BASELINE_SOURCES)),
            impact=impact,
            confidence=confidence,
            risk=risk,
        )

        # Пересчитываем прогнозы «с нуля» (append-only таблица очищается для этой симуляции).
        repo.delete_forecasts(db, simulation_id)
        created = 0
        for metric in _FORECAST_METRICS:
            baseline_value = float(baseline.get(metric, 0.0) or 0.0)
            for days in _HORIZON_DAYS:
                forecast_value, change_percent = self._project_metric(
                    metric, baseline_value, impact, risk, days
                )
                horizon_conf = self._confidence_at_horizon(base_conf, days)
                repo.create_forecast(
                    db,
                    simulation_id=simulation_id,
                    metric=metric,
                    period=_DAYS_TO_PERIOD[days],
                    baseline_value=baseline_value,
                    forecast_value=forecast_value,
                    change_percent=change_percent,
                    confidence_score=horizon_conf,
                    reasoning=self._forecast_reasoning(
                        metric, baseline_value, change_percent, impact, risk, days
                    ),
                )
                created += 1

        overall_score = self._strategy_score(db, simulation.project_id, impact, confidence, risk)
        confidence_level = self._confidence_level(base_conf)
        repo.update_simulation(
            db,
            simulation,
            status="completed",
            overall_score=overall_score,
            confidence_level=confidence_level,
        )
        self._write_audit(
            db,
            audit_actions.ACTION_SIMULATION_COMPLETED,
            simulation.project_id,
            user_id,
            simulation.id,
            {"forecasts": created, "overall_score": overall_score},
        )
        return {
            "simulation": repo.public_simulation_view(self._require_simulation(db, simulation_id)),
            "forecast": [
                repo.public_forecast_view(f) for f in repo.list_forecasts(db, simulation_id)
            ],
            "confidence": base_conf,
            "note": "Прогноз — модельная оценка, не финансовая гарантия.",
        }

    def calculate_forecast_confidence(
        self,
        *,
        sources_with_data: int,
        sources_total: int,
        impact: float,
        confidence: float,
        risk: float,
    ) -> float:
        """Уверенность прогноза 0..100: полнота данных + стабильность (риск) + качество сигнала."""
        data_score = (sources_with_data / sources_total * 100.0) if sources_total else 0.0
        stability = 100.0 - self._clamp(risk, 0.0, 100.0)
        signal_quality = self._clamp(confidence, 0.0, 100.0)
        raw = 0.4 * signal_quality + 0.35 * data_score + 0.25 * stability
        return round(self._clamp(raw, 0.0, 100.0), 1)

    # ------------------------------------------------------------------ #
    # Сравнение сценариев + рекомендация                                 #
    # ------------------------------------------------------------------ #

    def compare_scenarios(
        self, db: Session, decision_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Сравнить сценарии решения по Strategy Score = Impact × Confidence − Risk."""
        decision = self._require_decision(db, decision_id)
        risk_averse = self._is_risk_averse(db, decision.project_id, decision)
        scenarios = [
            s for s in decision_repo.list_scenarios(db, decision_id) if s.status != "rejected"
        ]
        if not scenarios:
            raise AIStrategySimulatorError("Нет сценариев для сравнения")

        scored: list[dict[str, Any]] = []
        for scenario in scenarios:
            impact, confidence, risk = self._scenario_signals(scenario)
            score = self._score(impact, confidence, risk, risk_averse)
            scored.append(
                {
                    "scenario_id": scenario.id,
                    "title": scenario.title,
                    "impact": round(impact, 1),
                    "confidence": round(confidence, 1),
                    "risk": round(risk, 1),
                    "strategy_score": score,
                }
            )
        scored.sort(key=lambda item: item["strategy_score"], reverse=True)
        winner = scored[0]
        runner_up = scored[1] if len(scored) > 1 else None
        # Отрыв — это разрыв до следующего варианта; без альтернатив отрыва нет (0.0), а не
        # абсолютный score победителя (иначе одиночный сценарий выглядел бы «уверенным лидером»).
        score_difference = (
            round(winner["strategy_score"] - runner_up["strategy_score"], 1) if runner_up else 0.0
        )
        reasoning = self._comparison_reasoning(scored, risk_averse)

        comparison = repo.create_comparison(
            db,
            decision_id=decision_id,
            winner_scenario_id=winner["scenario_id"],
            comparison_data={"scenarios": scored, "risk_averse": risk_averse},
            score_difference=score_difference,
            reasoning=reasoning,
        )
        self._write_audit(
            db,
            audit_actions.ACTION_SIMULATION_COMPARED,
            decision.project_id,
            user_id,
            comparison.id,
            {"decision_id": decision_id, "winner_scenario_id": winner["scenario_id"]},
        )
        return repo.public_comparison_view(comparison)

    def recommend_strategy(
        self, db: Session, decision_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Рекомендовать стратегию: {winner, confidence, reason}. Только совет, НЕ выполнение."""
        decision = self._require_decision(db, decision_id)
        comparison = repo.get_scenario_comparison(db, decision_id)
        # Пересчитываем, если сравнения нет ИЛИ оно устарело (сценарий отклонён после сравнения) —
        # иначе рекомендация могла бы вернуть уже отклонённый сценарий как победителя.
        if comparison is None or self._comparison_has_rejected(db, comparison):
            comparison_view = self.compare_scenarios(db, decision_id, user_id=user_id)
        else:
            comparison_view = repo.public_comparison_view(comparison)

        scenarios = comparison_view.get("comparison_data", {}).get("scenarios", [])
        if not scenarios:
            raise AIStrategySimulatorError("Нет данных сравнения для рекомендации")
        winner = scenarios[0]
        winner_scenario = decision_repo.get_scenario(db, winner["scenario_id"])
        winner_view = (
            decision_repo.public_scenario_view(winner_scenario)
            if winner_scenario is not None
            else None
        )
        reason = self._recommendation_reason(winner, comparison_view.get("score_difference", 0.0))
        self._write_audit(
            db,
            audit_actions.ACTION_SIMULATION_RECOMMENDED,
            decision.project_id,
            user_id,
            comparison_view.get("id"),
            {"decision_id": decision_id, "winner_scenario_id": winner["scenario_id"]},
        )
        return {
            "decision_id": decision_id,
            "winner": winner_view,
            "winner_score": winner["strategy_score"],
            "confidence": round(float(winner.get("confidence", 0.0) or 0.0), 1),
            "score_difference": comparison_view.get("score_difference", 0.0),
            "reason": reason,
            "note": "Рекомендация носит совещательный характер; решение принимает владелец.",
        }

    def _comparison_has_rejected(self, db: Session, comparison: ScenarioComparison) -> bool:
        """Ссылается ли сохранённое сравнение на уже отклонённый сценарий (устарело ли оно)."""
        for entry in (comparison.comparison_data or {}).get("scenarios", []):
            scenario = decision_repo.get_scenario(db, entry.get("scenario_id"))
            if scenario is not None and scenario.status == "rejected":
                return True
        return False

    def explain_forecast(self, db: Session, simulation_id: int) -> dict[str, Any]:
        """Объяснить прогноз владельцу: почему модель ожидает такой результат."""
        simulation = self._require_simulation(db, simulation_id)
        scenario = self._require_scenario(db, simulation.scenario_id)
        impact, confidence, risk = self._scenario_signals(scenario)
        forecasts = repo.list_forecasts(db, simulation_id)
        reasons: list[str] = [
            f"Сценарий «{scenario.title}»: эффект {round(impact, 1)}, уверенность "
            f"{round(confidence, 1)}, риск {round(risk, 1)}.",
        ]
        # Итог по метрикам на дальнем горизонте (90 дней).
        for forecast in forecasts:
            if forecast.period != "90_days" or not forecast.baseline_value:
                continue
            reasons.append(
                f"{forecast.metric}: {round(forecast.baseline_value, 1)} → "
                f"{round(forecast.forecast_value, 1)} ({forecast.change_percent:+.1f}% за 90 дней)."
            )
        if len(reasons) == 1:
            reasons.append(
                "Недостаточно базовых данных — запустите симуляцию (run) или добавьте метрики."
            )
        reasons.append("Прогноз — модельная оценка, не финансовая гарантия.")
        return {"simulation_id": simulation_id, "reasons": reasons}

    # ------------------------------------------------------------------ #
    # Модель прогноза                                                    #
    # ------------------------------------------------------------------ #

    def _project_metric(
        self, metric: str, baseline_value: float, impact: float, risk: float, days: int
    ) -> tuple[float, float]:
        """Спрогнозировать метрику: (forecast_value, change_percent) на горизонте `days`."""
        if baseline_value <= 0:
            return 0.0, 0.0
        impact01 = self._clamp(impact, 0.0, 100.0) / 100.0
        risk01 = self._clamp(risk, 0.0, 100.0) / 100.0
        responsiveness = _METRIC_RESPONSIVENESS.get(metric, 0.5)
        months = _DAYS_TO_MONTHS.get(days, 1.0)
        monthly_lift = _MAX_MONTHLY_LIFT * impact01 * responsiveness * (1.0 - 0.5 * risk01)
        cumulative = monthly_lift * (months**0.9)  # мягко убывающая отдача
        forecast_value = baseline_value * (1.0 + cumulative)
        return round(forecast_value, 2), round(cumulative * 100.0, 1)

    def _confidence_at_horizon(self, base_conf: float, days: int) -> float:
        """Уверенность падает с горизонтом (дальше — менее уверенно)."""
        months = _DAYS_TO_MONTHS.get(days, 1.0)
        decayed = base_conf * (1.0 - 0.05 * (months - 1.0))
        return round(self._clamp(decayed, 0.0, 100.0), 1)

    def _strategy_score(
        self, db: Session, project_id: int, impact: float, confidence: float, risk: float
    ) -> float:
        """Итоговая оценка стратегии симуляции (Strategy Score с учётом предпочтений владельца)."""
        risk_averse = self._is_risk_averse(db, project_id, None)
        return self._score(impact, confidence, risk, risk_averse)

    @staticmethod
    def _score(impact: float, confidence: float, risk: float, risk_averse: bool) -> float:
        """Strategy Score = impact × (confidence/100) − risk penalty, clamp [0..100]."""
        risk_weight = 0.5 if risk_averse else 0.3
        raw = impact * (confidence / 100.0) - risk_weight * risk
        return round(max(0.0, min(100.0, raw)), 1)

    @staticmethod
    def _scenario_signals(scenario: DecisionScenario) -> tuple[float, float, float]:
        """Достать (impact, confidence, risk) из сценария решения."""
        impact = float((scenario.expected_impact or {}).get("impact", 0.0) or 0.0)
        confidence = float(scenario.confidence_score or 0.0)
        risk = float((scenario.risk_analysis or {}).get("risk", 0.0) or 0.0)
        return impact, confidence, risk

    @staticmethod
    def _confidence_level(confidence: float) -> str:
        if confidence < 40.0:
            return "low"
        if confidence < 70.0:
            return "medium"
        return "high"

    @staticmethod
    def _forecast_reasoning(
        metric: str,
        baseline_value: float,
        change_percent: float,
        impact: float,
        risk: float,
        days: int,
    ) -> list[str]:
        if baseline_value <= 0:
            return [f"Нет базовых данных по «{metric}» — прогноз не построен."]
        return [
            f"База «{metric}»: {round(baseline_value, 2)} за {days} дн.",
            f"Ожидаемый эффект сценария {round(impact, 1)}, риск {round(risk, 1)} → "
            f"изменение {change_percent:+.1f}%.",
            "Модельная оценка, не финансовая гарантия.",
        ]

    def _comparison_reasoning(self, scored: list[dict[str, Any]], risk_averse: bool) -> list[str]:
        reasons: list[str] = []
        if scored:
            winner = scored[0]
            reasons.append(
                f"Лидер «{winner['title']}» — Strategy Score {winner['strategy_score']}/100 "
                f"(эффект {winner['impact']}, уверенность {winner['confidence']}, "
                f"риск {winner['risk']})."
            )
        if len(scored) > 1:
            reasons.append(
                f"Отрыв от следующего варианта: "
                f"{round(scored[0]['strategy_score'] - scored[1]['strategy_score'], 1)} балла."
            )
        if risk_averse:
            reasons.append("Учтены предпочтения владельца — повышен вес риска.")
        reasons.append("Сравнение носит совещательный характер; выбор за владельцем.")
        return reasons

    @staticmethod
    def _recommendation_reason(winner: dict[str, Any], score_difference: float) -> str:
        if float(winner.get("risk", 0.0) or 0.0) < 35.0:
            base = "Лучший баланс эффекта и риска"
        else:
            base = "Наибольший ожидаемый эффект; риск выше среднего — контролируйте выполнение"
        if score_difference >= 10.0:
            return f"{base}; уверенный отрыв от альтернатив."
        return f"{base}; отрыв невелик — рассмотрите альтернативы."

    # ------------------------------------------------------------------ #
    # Предпочтения владельца (Chief of Staff)                            #
    # ------------------------------------------------------------------ #

    def _is_risk_averse(self, db: Session, project_id: int, decision: Any) -> bool:
        """Осторожен ли владелец к риску (Decision context ИЛИ Chief of Staff)."""
        if decision is not None and bool(
            (getattr(decision, "context", None) or {}).get("owner_risk_averse")
        ):
            return True
        try:
            from app.services.ai_chief_of_staff_service import AIChiefOfStaffService

            context = AIChiefOfStaffService(
                settings=self._resolve_settings()
            ).build_decision_context(db, project_id)
            return bool(context.get("restrictions"))
        except Exception as exc:  # noqa: BLE001 — отсутствие слоя не роняет симуляцию
            logger.warning("simulator owner context failed: %s", type(exc).__name__)
            return False

    # ------------------------------------------------------------------ #
    # Инфраструктура                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, float(value)))

    def _require_project(self, db: Session, project_id: int) -> Any:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise AIStrategySimulatorError(f"Проект id={project_id} не найден")
        return project

    def _require_simulation(self, db: Session, simulation_id: int) -> StrategySimulation:
        simulation = repo.get_simulation(db, simulation_id)
        if simulation is None:
            raise AIStrategySimulatorError("Симуляция не найдена")
        return simulation

    def _require_scenario(self, db: Session, scenario_id: int) -> DecisionScenario:
        scenario = decision_repo.get_scenario(db, scenario_id)
        if scenario is None:
            raise AIStrategySimulatorError("Сценарий не найден")
        return scenario

    def _require_decision(self, db: Session, decision_id: int) -> Any:
        decision = decision_repo.get_decision(db, decision_id)
        if decision is None:
            raise AIStrategySimulatorError("Решение не найдено")
        return decision

    def _require_scenario_in_project(
        self, db: Session, scenario_id: int, project_id: int
    ) -> DecisionScenario:
        """Сценарий существует И принадлежит решению этого проекта (tenant isolation)."""
        scenario = self._require_scenario(db, scenario_id)
        decision = self._require_decision(db, scenario.decision_id)
        if decision.project_id != project_id:
            raise AIStrategySimulatorError("Сценарий не принадлежит этому проекту")
        return scenario

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
            entity_type="strategy_simulation",
            entity_id=entity_id,
            metadata=metadata,
        )


def get_ai_strategy_simulator_service() -> AIStrategySimulatorService:
    """DI-фабрика AI Strategy Simulator."""
    return AIStrategySimulatorService()
