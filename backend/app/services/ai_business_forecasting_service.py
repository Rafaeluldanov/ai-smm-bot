"""AIBusinessForecastingService — AI Business Forecasting Engine (v0.7.6).

Прогнозирует развитие бизнеса на 3/6/12 месяцев на основе текущего состояния (Operations
Snapshot), стратегических симуляций (Strategy Simulator) и истории решений (Decision Engine):
собирает baseline, проецирует KPI, вносит поправку на риск и строит бизнес-outlook + roadmap.

Поток: **Business State → Forecast Model → KPI Projection → Risk Adjustment → Business
Outlook → Owner Review**.

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- это аналитический прогнозный слой: только прогнозирует и советует;
- НЕ гарантирует прибыль/финансовый результат (прогноз — модельная оценка);
- НЕ меняет бизнес/CRM/бюджет, НЕ выполняет стратегии, НЕ ходит во внешние API;
- строго per-project; секретов нет; бесплатно (0 units);
- каждое изменение (created/generated/metric_created/roadmap_created) пишется в AuditLog.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import business_forecast_repository as repo
from app.repositories import project_repository
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.business_forecast import BusinessForecast
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

# Горизонты прогноза в месяцах.
_HORIZON_TO_MONTHS: dict[str, int] = {"3_months": 3, "6_months": 6, "12_months": 12}
# Все горизонты для outlook (forecast_state).
_OUTLOOK_HORIZONS: tuple[str, ...] = ("3_months", "6_months", "12_months")

# Бизнес-метрики прогноза и их отзывчивость на рост (0..1): выручка/лиды растут сильнее,
# чем конверсия/эффективность.
_METRIC_RESPONSIVENESS: dict[str, float] = {
    "revenue": 1.0,
    "leads": 0.9,
    "customers": 0.85,
    "traffic": 0.8,
    "conversion": 0.5,
    "efficiency": 0.45,
}
_BUSINESS_METRICS: tuple[str, ...] = (
    "revenue",
    "leads",
    "customers",
    "conversion",
    "traffic",
    "efficiency",
)

# Максимальный месячный рост при полном импульсе (growth_score=100) и нулевом риске (6%/мес).
_MAX_MONTHLY_GROWTH = 0.06
# Число источников baseline (для оценки полноты данных).
_BASELINE_SOURCES = 3


class AIBusinessForecastingError(Exception):
    """Ошибка Business Forecasting (нет проекта/прогноза) — API → 400/404."""


class AIBusinessForecastingService:
    """AI-движок прогноза бизнеса: baseline → projection → risk → outlook → roadmap."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Прогнозы: создание / чтение                                        #
    # ------------------------------------------------------------------ #

    def create_forecast(
        self,
        db: Session,
        project_id: int,
        *,
        horizon: str = "12_months",
        title: str | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Создать прогноз из текущего состояния бизнеса. НЕ запускает проекцию (advisory)."""
        from app.models.business_forecast import FORECAST_HORIZONS

        self._require_project(db, project_id)
        if horizon not in FORECAST_HORIZONS:
            raise AIBusinessForecastingError("Неизвестный горизонт прогноза")

        baseline = self.collect_business_baseline(db, project_id)
        clean_title = (title or "").strip() or f"Прогноз бизнеса ({horizon})"
        forecast = repo.create_forecast(
            db,
            project_id=project_id,
            account_id=self._account_id(db, project_id),
            title=clean_title,
            horizon=horizon,
            status="generated",
            baseline_state=baseline,
            risk_level="medium",
        )
        self._write_audit(
            db,
            audit_actions.ACTION_FORECAST_CREATED,
            project_id,
            user_id,
            forecast.id,
            {"horizon": horizon},
        )
        return repo.public_forecast_view(forecast)

    def list_forecasts(
        self, db: Session, project_id: int, status: str | None = None
    ) -> list[dict[str, Any]]:
        """Список прогнозов проекта (по статусу)."""
        self._require_project(db, project_id)
        return [
            repo.public_forecast_view(f) for f in repo.list_forecasts(db, project_id, status=status)
        ]

    def get_forecast(self, db: Session, forecast_id: int) -> dict[str, Any]:
        """Прогноз + метрики + roadmap."""
        forecast = self._require_forecast(db, forecast_id)
        roadmap = repo.get_roadmap(db, forecast_id)
        return {
            "forecast": repo.public_forecast_view(forecast),
            "metrics": [repo.public_metric_view(m) for m in repo.list_metrics(db, forecast_id)],
            "roadmap": repo.public_roadmap_view(roadmap) if roadmap is not None else None,
        }

    def get_metrics(self, db: Session, forecast_id: int) -> list[dict[str, Any]]:
        """KPI-проекции прогноза."""
        self._require_forecast(db, forecast_id)
        return [repo.public_metric_view(m) for m in repo.list_metrics(db, forecast_id)]

    def get_roadmap(self, db: Session, forecast_id: int) -> dict[str, Any] | None:
        """Roadmap прогноза (или None)."""
        self._require_forecast(db, forecast_id)
        roadmap = repo.get_roadmap(db, forecast_id)
        return repo.public_roadmap_view(roadmap) if roadmap is not None else None

    def get_summary(self, db: Session, project_id: int) -> dict[str, Any]:
        """Сводка Business Forecasting (для UI-состояния)."""
        self._require_project(db, project_id)
        return repo.build_forecast_summary(db, project_id)

    def get_business_outlook(self, db: Session, project_id: int) -> dict[str, Any]:
        """Бизнес-outlook проекта: последний прогноз + baseline + метрики + roadmap."""
        self._require_project(db, project_id)
        latest = repo.get_latest_forecast(db, project_id)
        if latest is None:
            return {
                "project_id": project_id,
                "forecast": None,
                "baseline": self.collect_business_baseline(db, project_id),
                "metrics": [],
                "roadmap": None,
                "note": "Прогнозов ещё нет — создайте прогноз (create) и запустите генерацию.",
            }
        roadmap = repo.get_roadmap(db, latest.id)
        return {
            "project_id": project_id,
            "forecast": repo.public_forecast_view(latest),
            "baseline": dict(latest.baseline_state or {}),
            "metrics": [repo.public_metric_view(m) for m in repo.list_metrics(db, latest.id)],
            "roadmap": repo.public_roadmap_view(roadmap) if roadmap is not None else None,
        }

    # ------------------------------------------------------------------ #
    # Baseline: текущее состояние бизнеса                                 #
    # ------------------------------------------------------------------ #

    def collect_business_baseline(self, db: Session, project_id: int) -> dict[str, Any]:
        """Собрать базовое состояние бизнеса из смежных слоёв.

        Возвращает {revenue, leads, customers, conversion, traffic, efficiency, growth_score,
        workflow_progress, health_score} + метаданные полноты данных. Каждый источник в
        try/except — отсутствие слоя не роняет прогноз.
        """
        baseline: dict[str, float] = {
            "revenue": 0.0,
            "leads": 0.0,
            "customers": 0.0,
            "conversion": 0.0,
            "traffic": 0.0,
            "efficiency": 0.0,
            "growth_score": 0.0,
            "workflow_progress": 0.0,
            "health_score": 0.0,
        }
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
            baseline["growth_score"] = float(state.get("growth_score", 0.0) or 0.0)
            baseline["efficiency"] = baseline["growth_score"]
            # Клиенты ≈ сконвертированные лиды (модельная оценка, не CRM).
            baseline["customers"] = round(baseline["leads"] * baseline["conversion"], 2)
            if baseline["revenue"] or baseline["leads"] or baseline["growth_score"]:
                sources_with_data += 1
        except Exception as exc:  # noqa: BLE001 — нижний слой не должен ронять baseline
            logger.warning("forecasting executive baseline failed: %s", type(exc).__name__)

        # Analytics: traffic (reach).
        try:
            from app.services.analytics_service import AnalyticsService

            summary = AnalyticsService().get_project_summary(db, project_id)
            baseline["traffic"] = float(getattr(summary, "total_reach", 0) or 0)
            if baseline["traffic"]:
                sources_with_data += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("forecasting analytics baseline failed: %s", type(exc).__name__)

        # Operations Center: health-score + прогресс процессов.
        try:
            from app.repositories import operations_repository as ops_repo

            snapshot = ops_repo.get_latest_snapshot(db, project_id)
            if snapshot is not None:
                baseline["health_score"] = float(snapshot.health_score or 0.0)
                metrics = snapshot.metrics or {}
                baseline["workflow_progress"] = float(metrics.get("workflow_progress", 0.0) or 0.0)
                if not baseline["efficiency"]:
                    baseline["efficiency"] = baseline["health_score"]
                sources_with_data += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("forecasting operations baseline failed: %s", type(exc).__name__)

        return {
            **{k: round(v, 2) for k, v in baseline.items()},
            "_meta": {
                "sources_with_data": sources_with_data,
                "sources_total": _BASELINE_SOURCES,
            },
        }

    # ------------------------------------------------------------------ #
    # Генерация прогноза (проекция + риск + outlook + roadmap)            #
    # ------------------------------------------------------------------ #

    def generate_business_outlook(
        self, db: Session, forecast_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Запустить генерацию: baseline → проекция KPI (3/6/12) → риск → outlook → roadmap.

        НЕ гарантирует результат: forecast_value — модельная оценка. НЕ меняет бизнес/CRM/бюджет.
        """
        forecast = self._require_forecast(db, forecast_id)
        baseline = self.collect_business_baseline(db, forecast.project_id)
        meta = baseline.get("_meta", {})
        growth_score = float(baseline.get("growth_score", 0.0) or 0.0)

        risk = self.apply_risk_adjustment(db, forecast.project_id)
        risk_penalty = float(risk["risk_penalty"])
        risk_level = str(risk["risk_level"])

        history_count = len(repo.list_forecasts(db, forecast.project_id))
        confidence = self.calculate_confidence(
            sources_with_data=int(meta.get("sources_with_data", 0)),
            sources_total=int(meta.get("sources_total", _BASELINE_SOURCES)),
            growth_score=growth_score,
            risk_penalty=risk_penalty,
            history_count=history_count,
        )

        # Многогоризонтный outlook (forecast_state) по ключевым метрикам.
        forecast_state = self._build_outlook(baseline, growth_score, risk_penalty, confidence)

        # KPI-проекции (per-metric) на выбранном горизонте прогноза.
        months = _HORIZON_TO_MONTHS.get(forecast.horizon, 12)
        repo.delete_metrics(db, forecast_id)
        for metric in _BUSINESS_METRICS:
            baseline_value = float(baseline.get(metric, 0.0) or 0.0)
            forecast_value, change_percent = self.project_metric(
                metric, baseline_value, growth_score, risk_penalty, months
            )
            repo.create_metric(
                db,
                forecast_id=forecast_id,
                metric=metric,
                baseline_value=baseline_value,
                forecast_value=forecast_value,
                change_percent=change_percent,
                confidence_score=confidence,
                reasoning=self._metric_reasoning(
                    metric, baseline_value, change_percent, growth_score, risk_level, months
                ),
            )
        self._write_audit(
            db,
            audit_actions.ACTION_FORECAST_METRIC_CREATED,
            forecast.project_id,
            user_id,
            forecast_id,
            {"metrics": len(_BUSINESS_METRICS)},
        )

        assumptions = self._assumptions(baseline, growth_score, risk, confidence)
        repo.update_forecast(
            db,
            forecast,
            forecast_state=forecast_state,
            baseline_state=baseline,
            assumptions=assumptions,
            risk_level=risk_level,
            confidence_score=confidence,
            generated_at=self._now(),
        )

        self.create_business_roadmap(db, forecast_id, baseline, forecast_state, risk, user_id)

        self._write_audit(
            db,
            audit_actions.ACTION_FORECAST_GENERATED,
            forecast.project_id,
            user_id,
            forecast_id,
            {"risk_level": risk_level, "confidence": confidence},
        )
        return {
            "forecast": repo.public_forecast_view(self._require_forecast(db, forecast_id)),
            "metrics": [repo.public_metric_view(m) for m in repo.list_metrics(db, forecast_id)],
            "roadmap": self.get_roadmap(db, forecast_id),
            "confidence": confidence,
            "note": "Прогноз — модельная оценка, не финансовая гарантия.",
        }

    def project_metric(
        self,
        metric: str,
        baseline_value: float,
        growth_score: float,
        risk_penalty: float,
        months: int,
    ) -> tuple[float, float]:
        """Спрогнозировать метрику: (forecast_value, change_percent) на `months` месяцев.

        Revenue ≈ baseline × (1 + monthly_growth)^months; monthly_growth растёт с growth_score и
        отзывчивостью метрики, падает с риском.
        """
        if baseline_value <= 0:
            return 0.0, 0.0
        growth01 = self._clamp(growth_score, 0.0, 100.0) / 100.0
        risk01 = self._clamp(risk_penalty, 0.0, 100.0) / 100.0
        responsiveness = _METRIC_RESPONSIVENESS.get(metric, 0.5)
        monthly_growth = _MAX_MONTHLY_GROWTH * growth01 * responsiveness * (1.0 - risk01)
        factor = (1.0 + monthly_growth) ** months
        forecast_value = baseline_value * factor
        return round(forecast_value, 2), round((factor - 1.0) * 100.0, 1)

    def calculate_confidence(
        self,
        *,
        sources_with_data: int,
        sources_total: int,
        growth_score: float,
        risk_penalty: float,
        history_count: int,
    ) -> float:
        """Уверенность прогноза 0..100: данные + стабильность + сигнал + история прогнозов."""
        data_score = (sources_with_data / sources_total * 100.0) if sources_total else 0.0
        stability = 100.0 - self._clamp(risk_penalty, 0.0, 100.0)
        signal_quality = self._clamp(growth_score, 0.0, 100.0)
        history_score = min(100.0, max(0, history_count) * 25.0)
        raw = 0.30 * data_score + 0.25 * stability + 0.30 * signal_quality + 0.15 * history_score
        return round(self._clamp(raw, 0.0, 100.0), 1)

    def apply_risk_adjustment(self, db: Session, project_id: int) -> dict[str, Any]:
        """Поправка на риск: Operations Risks + Workflow Blockers + Decision Risks → штраф+уровень.

        Возвращает {risk_penalty, risk_level, signals}. Каждый источник в try/except.
        """
        operations_risks = 0
        workflow_blockers = 0
        decision_risks = 0
        health_score = 100.0

        # Operations Center: открытые риски + health.
        try:
            from app.repositories import operations_repository as ops_repo

            operations_risks = len(ops_repo.list_active_risks(db, project_id))
            snapshot = ops_repo.get_latest_snapshot(db, project_id)
            if snapshot is not None:
                health_score = float(snapshot.health_score or 0.0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("forecasting operations risk failed: %s", type(exc).__name__)

        # Workflow Manager: открытые блокеры по активным процессам.
        try:
            from app.repositories import workflow_repository as wf_repo

            active = wf_repo.get_active_workflows(db, project_id)
            workflow_blockers = sum(
                len(wf_repo.list_blockers(db, w.id, status="open")) for w in active
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("forecasting workflow risk failed: %s", type(exc).__name__)

        # Decision Engine: недавние решения повышенного риска (по сценариям).
        try:
            from app.repositories import decision_repository as decision_repo

            for decision in decision_repo.list_decisions(db, project_id, limit=20):
                scenarios = decision_repo.list_scenarios(db, decision.id)
                if any(
                    float((s.risk_analysis or {}).get("risk", 0.0) or 0.0) >= 60.0
                    for s in scenarios
                ):
                    decision_risks += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("forecasting decision risk failed: %s", type(exc).__name__)

        health_deficit = max(0.0, 70.0 - health_score) * 0.3
        raw_penalty = (
            operations_risks * 8.0 + workflow_blockers * 5.0 + decision_risks * 4.0 + health_deficit
        )
        risk_penalty = round(self._clamp(raw_penalty, 0.0, 50.0), 1)
        return {
            "risk_penalty": risk_penalty,
            "risk_level": self._risk_level(risk_penalty),
            "signals": {
                "operations_risks": operations_risks,
                "workflow_blockers": workflow_blockers,
                "decision_risks": decision_risks,
                "health_score": round(health_score, 1),
            },
        }

    # ------------------------------------------------------------------ #
    # Roadmap + объяснение                                               #
    # ------------------------------------------------------------------ #

    def create_business_roadmap(
        self,
        db: Session,
        forecast_id: int,
        baseline: dict[str, Any] | None = None,
        forecast_state: dict[str, Any] | None = None,
        risk: dict[str, Any] | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Построить квартальный roadmap прогноза (цели/вехи/риски/рекомендации)."""
        forecast = self._require_forecast(db, forecast_id)
        base = baseline if baseline is not None else dict(forecast.baseline_state or {})
        outlook = (
            forecast_state if forecast_state is not None else dict(forecast.forecast_state or {})
        )
        risk_bundle = (
            risk if risk is not None else self.apply_risk_adjustment(db, forecast.project_id)
        )

        quarters = self._roadmap_quarters(base)
        milestones = self._roadmap_milestones(outlook)
        risks = self._roadmap_risks(risk_bundle)
        recommendations = self._roadmap_recommendations(base)

        repo.delete_roadmaps(db, forecast_id)
        roadmap = repo.create_roadmap(
            db,
            forecast_id=forecast_id,
            title=f"Roadmap: {forecast.title}",
            quarters=quarters,
            milestones=milestones,
            risks=risks,
            recommendations=recommendations,
        )
        self._write_audit(
            db,
            audit_actions.ACTION_FORECAST_ROADMAP_CREATED,
            forecast.project_id,
            user_id,
            forecast_id,
            {"quarters": len(quarters)},
        )
        return repo.public_roadmap_view(roadmap)

    def explain_forecast(self, db: Session, forecast_id: int) -> dict[str, Any]:
        """Объяснить владельцу: почему AI прогнозирует такой рост."""
        forecast = self._require_forecast(db, forecast_id)
        baseline = dict(forecast.baseline_state or {})
        growth = round(float(baseline.get("growth_score", 0.0)), 1)
        health = round(float(baseline.get("health_score", 0.0)), 1)
        reasons: list[str] = [
            f"Импульс роста (Growth Score) {growth}/100 и health {health}/100 задают базовый темп.",
            f"Уровень риска: {forecast.risk_level} — влияет на поправку прогноза.",
            f"Уверенность прогноза: {round(float(forecast.confidence_score or 0.0), 1)}/100 "
            f"(данные + стабильность + сигнал + история).",
        ]
        metrics = repo.list_metrics(db, forecast_id)
        for m in metrics:
            if m.metric == "revenue" and m.baseline_value:
                reasons.append(
                    f"Выручка: {round(m.baseline_value, 1)} → {round(m.forecast_value, 1)} "
                    f"({m.change_percent:+.1f}% за {forecast.horizon})."
                )
        if len(reasons) == 3:
            reasons.append("Недостаточно базовых данных — запустите генерацию (generate).")
        reasons.append("Прогноз — модельная оценка, не финансовая гарантия.")
        return {"forecast_id": forecast_id, "reasons": reasons}

    # ------------------------------------------------------------------ #
    # Построение outlook / roadmap-контента                              #
    # ------------------------------------------------------------------ #

    def _build_outlook(
        self,
        baseline: dict[str, Any],
        growth_score: float,
        risk_penalty: float,
        confidence: float,
    ) -> dict[str, Any]:
        """Многогоризонтный outlook: изменение ключевых метрик на 3/6/12 месяцев."""
        headline = ("revenue", "leads", "customers", "conversion")
        outlook: dict[str, Any] = {}
        for horizon in _OUTLOOK_HORIZONS:
            months = _HORIZON_TO_MONTHS[horizon]
            horizon_block: dict[str, Any] = {}
            for metric in headline:
                baseline_value = float(baseline.get(metric, 0.0) or 0.0)
                _forecast_value, change_percent = self.project_metric(
                    metric, baseline_value, growth_score, risk_penalty, months
                )
                horizon_block[metric] = change_percent
            outlook[horizon] = horizon_block
        outlook["confidence"] = confidence
        return outlook

    def _roadmap_quarters(self, baseline: dict[str, Any]) -> list[dict[str, Any]]:
        """Квартальные фокусы (Q1–Q4), с учётом слабых мест baseline."""
        conversion = float(baseline.get("conversion", 0.0) or 0.0)
        revenue = float(baseline.get("revenue", 0.0) or 0.0)
        q1_goals = ["Стабилизировать текущие каналы", "Улучшить конверсию из контента"]
        if conversion <= 0:
            q1_goals.append("Наладить сбор метрик конверсии")
        q3_goals = ["Масштабировать работающие каналы"]
        if revenue > 0:
            q3_goals.append("Расширить каналы привлечения")
        return [
            {"quarter": "Q1", "focus": "Фундамент", "goals": q1_goals},
            {
                "quarter": "Q2",
                "focus": "Рост",
                "goals": ["Увеличить поток лидов", "Усилить продающий контент"],
            },
            {"quarter": "Q3", "focus": "Масштабирование", "goals": q3_goals},
            {
                "quarter": "Q4",
                "focus": "Закрепление",
                "goals": ["Оптимизировать юнит-экономику", "Закрепить рост"],
            },
        ]

    @staticmethod
    def _roadmap_milestones(outlook: dict[str, Any]) -> list[str]:
        """Вехи по горизонтам из outlook (ожидаемое изменение выручки)."""
        milestones: list[str] = []
        for horizon in _OUTLOOK_HORIZONS:
            block = outlook.get(horizon, {}) or {}
            rev_change = block.get("revenue")
            if rev_change is not None:
                milestones.append(f"{horizon}: ожидаемое изменение выручки {rev_change:+.1f}%")
        if not milestones:
            milestones.append("Недостаточно данных для вех — добавьте метрики выручки/лидов.")
        return milestones

    @staticmethod
    def _roadmap_risks(risk_bundle: dict[str, Any]) -> list[str]:
        """Риски roadmap из сигналов поправки на риск."""
        signals = risk_bundle.get("signals", {}) or {}
        risks: list[str] = [
            f"Общий уровень риска: {risk_bundle.get('risk_level', 'medium')} "
            f"(штраф {risk_bundle.get('risk_penalty', 0)})."
        ]
        if signals.get("operations_risks"):
            risks.append(f"Открытых операционных рисков: {signals['operations_risks']}.")
        if signals.get("workflow_blockers"):
            risks.append(f"Блокеров в процессах: {signals['workflow_blockers']}.")
        if signals.get("decision_risks"):
            risks.append(f"Решений повышенного риска: {signals['decision_risks']}.")
        return risks

    @staticmethod
    def _roadmap_recommendations(baseline: dict[str, Any]) -> list[str]:
        """Рекомендации roadmap по слабым метрикам baseline (только советы)."""
        recs: list[str] = []
        if float(baseline.get("conversion", 0.0) or 0.0) <= 0:
            recs.append("Наладить измерение конверсии — без неё прогноз менее точен.")
        if float(baseline.get("leads", 0.0) or 0.0) <= 0:
            recs.append("Запустить генерацию лидов из контента.")
        if float(baseline.get("revenue", 0.0) or 0.0) <= 0:
            recs.append("Сфокусироваться на первых продажах из контента.")
        if float(baseline.get("growth_score", 0.0) or 0.0) < 50:
            recs.append("Усилить импульс роста: масштабировать работающие темы/каналы.")
        if not recs:
            recs.append("Удерживать темп: масштабировать то, что уже приносит результат.")
        return recs

    def _assumptions(
        self,
        baseline: dict[str, Any],
        growth_score: float,
        risk: dict[str, Any],
        confidence: float,
    ) -> list[str]:
        return [
            f"База: выручка {baseline.get('revenue', 0)}, лиды {baseline.get('leads', 0)}, "
            f"конверсия {baseline.get('conversion', 0)}.",
            f"Импульс роста (Growth Score): {round(growth_score, 1)}/100.",
            f"Уровень риска: {risk.get('risk_level')} (штраф {risk.get('risk_penalty')}).",
            f"Уверенность прогноза: {confidence}/100.",
            "Прогноз — модельная оценка, не финансовая гарантия.",
        ]

    @staticmethod
    def _metric_reasoning(
        metric: str,
        baseline_value: float,
        change_percent: float,
        growth_score: float,
        risk_level: str,
        months: int,
    ) -> list[str]:
        if baseline_value <= 0:
            return [f"Нет базовых данных по «{metric}» — прогноз не построен."]
        return [
            f"База «{metric}»: {round(baseline_value, 2)}.",
            f"Импульс {round(growth_score, 1)}/100, риск «{risk_level}» → "
            f"изменение {change_percent:+.1f}% за {months} мес.",
            "Модельная оценка, не финансовая гарантия.",
        ]

    @staticmethod
    def _risk_level(risk_penalty: float) -> str:
        if risk_penalty < 10.0:
            return "low"
        if risk_penalty < 25.0:
            return "medium"
        if risk_penalty < 40.0:
            return "high"
        return "critical"

    # ------------------------------------------------------------------ #
    # Инфраструктура                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, float(value)))

    def _require_project(self, db: Session, project_id: int) -> Any:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise AIBusinessForecastingError(f"Проект id={project_id} не найден")
        return project

    def _require_forecast(self, db: Session, forecast_id: int) -> BusinessForecast:
        forecast = repo.get_forecast(db, forecast_id)
        if forecast is None:
            raise AIBusinessForecastingError("Прогноз не найден")
        return forecast

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
            entity_type="business_forecast",
            entity_id=entity_id,
            metadata=metadata,
        )


def get_ai_business_forecasting_service() -> AIBusinessForecastingService:
    """DI-фабрика AI Business Forecasting Engine."""
    return AIBusinessForecastingService()
