"""AIOperationsControlService — AI Operations Control Center (v0.7.3).

Единая операционная панель бизнеса. Сводит состояние (рост, продажи, процессы, исполнение)
в один health-снапшот, детектит риски и генерирует рекомендации владельцу. Это
аналитический и управленческий слой.

Поток: **Collect Signals → Calculate Health → Detect Risks → Recommend → Owner Review**.

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- НЕ выполняет действия/рекомендации автоматически; resolve/accept/reject лишь меняют статус;
- НЕ меняет CRM/бюджет/продажи, НЕ запускает рекламу, НЕ публикует, НЕ включает live;
- НЕ совершает внешних действий; строго per-project; секретов нет; всё бесплатно (0 units);
- каждое изменение (snapshot_created/risk_*/recommendation_*) пишется в AuditLog.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import operations_repository as repo
from app.repositories import project_repository
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.operations_recommendation import OperationsRecommendation
    from app.models.operations_risk import OperationsRisk
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

# Веса компонентов health-score (в сумме 1.0).
_W_GROWTH = 0.35
_W_REVENUE = 0.25
_W_EXECUTION = 0.20
_W_WORKFLOW = 0.20
# Нейтральная база для execution/workflow_progress, когда процессов нет.
_NEUTRAL = 70.0
# Штраф здоровья по тяжести открытого риска.
_RISK_PENALTY: dict[str, float] = {"critical": 15.0, "high": 10.0, "medium": 6.0, "low": 3.0}
_RISK_PENALTY_CAP = 40.0

# Каталог рисков: (severity, заголовок, рекомендованное действие, приоритет рекомендации).
_RISK_CATALOG: dict[str, dict[str, str]] = {
    "workflow_delay": {
        "severity": "medium",
        "title": "Процессы без движения",
        "action": "Назначьте ответственных за застрявшие этапы и обновите сроки",
        "priority": "high",
    },
    "execution_block": {
        "severity": "high",
        "title": "Исполнение заблокировано",
        "action": "Снимите открытые блокеры процессов, чтобы возобновить работу",
        "priority": "critical",
    },
    "revenue_drop": {
        "severity": "high",
        "title": "Снижение выручки",
        "action": "Усильте продающий контент и CTA, проверьте работающие каналы",
        "priority": "critical",
    },
    "conversion_drop": {
        "severity": "medium",
        "title": "Падение конверсии",
        "action": "Пересмотрите офферы и путь лида (заявка → сделка)",
        "priority": "high",
    },
    "content_gap": {
        "severity": "medium",
        "title": "Провал в контенте",
        "action": "Обновите контент-стратегию: замените слабые темы работающими",
        "priority": "medium",
    },
    "missing_data": {
        "severity": "low",
        "title": "Недостаточно данных",
        "action": "Начните фиксировать лиды и выручку по постам для точных выводов",
        "priority": "medium",
    },
}


class AIOperationsControlError(Exception):
    """Ошибка Operations Center (нет проекта/риска/рекомендации) — API → 400/404."""


class AIOperationsControlService:
    """AI операционный центр: collect → health → risks → recommendations → review."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Снапшот + анализ                                                    #
    # ------------------------------------------------------------------ #

    def build_operations_snapshot(
        self, db: Session, project_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Собрать операционный снапшот: сигналы → health → риски → рекомендации."""
        self._require_project(db, project_id)
        signals = self._collect_signals(db, project_id, user_id)

        # Детект рисков ДО расчёта health (штраф зависит от открытых рисков).
        self._detect_risks(db, project_id, signals, user_id)
        open_risks = repo.list_active_risks(db, project_id)
        risk_penalty = self._risk_penalty(open_risks)

        components = self._components(signals)
        health_score = self.calculate_health_score(components, risk_penalty)
        status = self._health_status(health_score)

        snapshot = repo.create_snapshot(
            db,
            project_id=project_id,
            account_id=self._account_id(db, project_id),
            health_score=health_score,
            status=status,
            metrics={**components, "risk_penalty": risk_penalty},
            business_state=signals.get("business", {}),
            growth_state=signals.get("growth", {}),
            sales_state=signals.get("sales", {}),
            workflow_state=signals.get("workflow", {}),
            risk_count=len(open_risks),
        )
        self._write_audit(
            db,
            audit_actions.ACTION_OPERATIONS_SNAPSHOT_CREATED,
            project_id,
            user_id,
            snapshot.id,
            {"health_score": health_score, "status": status, "risks": len(open_risks)},
        )
        recommendations = self._generate_recommendations(db, project_id, open_risks, user_id)
        return {
            "snapshot": repo.public_snapshot_view(snapshot),
            "risks": [repo.public_risk_view(r) for r in open_risks],
            "recommendations": recommendations,
        }

    def calculate_health_score(self, components: dict[str, float], risk_penalty: float) -> float:
        """Health = Growth + Revenue + Execution + Workflow − Risk Penalty → 0..100."""
        base = (
            _W_GROWTH * components.get("growth", 0.0)
            + _W_REVENUE * components.get("revenue", 0.0)
            + _W_EXECUTION * components.get("execution", 0.0)
            + _W_WORKFLOW * components.get("workflow_progress", 0.0)
        )
        return round(max(0.0, min(100.0, base - risk_penalty)), 1)

    def get_operations(self, db: Session, project_id: int) -> dict[str, Any]:
        """Последний снапшот + открытые риски + рекомендации."""
        self._require_project(db, project_id)
        snapshot = repo.get_latest_snapshot(db, project_id)
        if snapshot is None:
            return {
                "project_id": project_id,
                "has_snapshot": False,
                "snapshot": None,
                "risks": [],
                "recommendations": [],
            }
        return {
            "project_id": project_id,
            "has_snapshot": True,
            "snapshot": repo.public_snapshot_view(snapshot),
            "risks": [repo.public_risk_view(r) for r in repo.list_active_risks(db, project_id)],
            "recommendations": [
                repo.public_recommendation_view(r)
                for r in repo.list_recommendations(db, project_id, status="generated")
            ],
        }

    def get_history(self, db: Session, project_id: int, limit: int = 30) -> list[dict[str, Any]]:
        """История операционных снапшотов (тренд health)."""
        self._require_project(db, project_id)
        return [
            repo.public_snapshot_view(s) for s in repo.list_snapshots(db, project_id, limit=limit)
        ]

    def get_summary(self, db: Session, project_id: int) -> dict[str, Any]:
        """Сводка операционного центра (для UI-состояния)."""
        self._require_project(db, project_id)
        return repo.build_operations_summary(db, project_id)

    # ------------------------------------------------------------------ #
    # Риски                                                              #
    # ------------------------------------------------------------------ #

    def list_active_risks(self, db: Session, project_id: int) -> list[dict[str, Any]]:
        """Открытые операционные риски проекта."""
        self._require_project(db, project_id)
        return [repo.public_risk_view(r) for r in repo.list_active_risks(db, project_id)]

    def resolve_risk(self, db: Session, risk_id: int, user_id: int | None = None) -> dict[str, Any]:
        """Снять риск (status=resolved). НЕ выполняет действий."""
        risk = self._require_risk(db, risk_id)
        if risk.status == "resolved":
            raise AIOperationsControlError("Риск уже снят")
        repo.resolve_risk(db, risk)
        self._write_audit(
            db,
            audit_actions.ACTION_OPERATIONS_RISK_RESOLVED,
            risk.project_id,
            user_id,
            risk.id,
            {},
        )
        return repo.public_risk_view(risk)

    def _detect_risks(
        self, db: Session, project_id: int, signals: dict[str, Any], user_id: int | None
    ) -> list[dict[str, Any]]:
        """Найти операционные риски по сигналам (дедуп по открытому риску того же типа)."""
        detected: list[str] = []
        wf = signals.get("workflow", {})
        sales = signals.get("sales", {})
        content = signals.get("content", {})
        prev = signals.get("prev", {})

        if int(wf.get("stuck_steps", 0) or 0) > 0 or int(wf.get("overdue_steps", 0) or 0) > 0:
            detected.append("workflow_delay")
        if int(wf.get("open_blockers", 0) or 0) > 0:
            detected.append("execution_block")
        # Сравнение с предыдущим снапшотом (тренд).
        if prev:
            if float(prev.get("revenue", 0) or 0) > float(sales.get("revenue", 0) or 0) + 1.0:
                detected.append("revenue_drop")
            if (
                float(prev.get("conversion", 0) or 0)
                > float(sales.get("conversion", 0) or 0) + 0.01
            ):
                detected.append("conversion_drop")
        # «Нет бизнес-данных» = нет выручки и нет лидов → это missing_data, а НЕ провал в
        # контенте: content_gap и missing_data взаимоисключимы по оси данных.
        has_business_data = (
            float(sales.get("revenue", 0) or 0) > 0 or int(sales.get("leads", 0) or 0) > 0
        )
        # content_gap только при наличии данных: слабые темы ИЛИ низкая-но-НЕнулевая
        # эффективность. Иначе data-scarcity weak_areas новых проектов ложно триггерили бы риск.
        efficiency = float(content.get("content_efficiency", 0.0) or 0.0)
        if has_business_data and (content.get("weak_areas") or (0.0 < efficiency < 30.0)):
            detected.append("content_gap")
        if not has_business_data:
            detected.append("missing_data")

        created: list[dict[str, Any]] = []
        account_id = self._account_id(db, project_id)
        for risk_type in detected:
            if repo.find_open_risk_by_type(db, project_id, risk_type) is not None:
                continue  # уже есть открытый риск этого типа
            spec = _RISK_CATALOG[risk_type]
            risk = repo.create_risk(
                db,
                project_id=project_id,
                account_id=account_id,
                risk_type=risk_type,
                title=spec["title"],
                severity=spec["severity"],
                description=spec["action"],
                source_module=self._risk_source(risk_type),
                impact={"health": "снижает"},
                recommended_action={"action": spec["action"]},
            )
            created.append(repo.public_risk_view(risk))
        if created:
            self._write_audit(
                db,
                audit_actions.ACTION_OPERATIONS_RISK_CREATED,
                project_id,
                user_id,
                None,
                {"created": len(created)},
            )
        return created

    @staticmethod
    def _risk_source(risk_type: str) -> str:
        if risk_type in ("workflow_delay", "execution_block"):
            return "workflow_manager"
        if risk_type in ("revenue_drop", "conversion_drop"):
            return "sales_intelligence"
        if risk_type == "content_gap":
            return "content_strategy"
        return "operations_center"

    # ------------------------------------------------------------------ #
    # Рекомендации                                                       #
    # ------------------------------------------------------------------ #

    def list_recommendations(
        self, db: Session, project_id: int, status: str | None = None
    ) -> list[dict[str, Any]]:
        """Операционные рекомендации проекта (по статусу)."""
        self._require_project(db, project_id)
        return [
            repo.public_recommendation_view(r)
            for r in repo.list_recommendations(db, project_id, status=status)
        ]

    def accept_recommendation(
        self, db: Session, recommendation_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Одобрить рекомендацию (status=accepted). НЕ выполняет действие."""
        rec = self._require_recommendation(db, recommendation_id)
        if rec.status != "generated":
            raise AIOperationsControlError("Рекомендация уже обработана")
        repo.accept_recommendation(db, rec)
        self._write_audit(
            db,
            audit_actions.ACTION_OPERATIONS_RECOMMENDATION_ACCEPTED,
            rec.project_id,
            user_id,
            rec.id,
            {},
        )
        return repo.public_recommendation_view(rec)

    def reject_recommendation(
        self, db: Session, recommendation_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Отклонить рекомендацию (status=rejected)."""
        rec = self._require_recommendation(db, recommendation_id)
        if rec.status != "generated":
            raise AIOperationsControlError("Рекомендация уже обработана")
        repo.reject_recommendation(db, rec)
        self._write_audit(
            db,
            audit_actions.ACTION_OPERATIONS_RECOMMENDATION_REJECTED,
            rec.project_id,
            user_id,
            rec.id,
            {},
        )
        return repo.public_recommendation_view(rec)

    def _generate_recommendations(
        self,
        db: Session,
        project_id: int,
        open_risks: list[OperationsRisk],
        user_id: int | None,
    ) -> list[dict[str, Any]]:
        """Создать рекомендации из открытых рисков (дедуп по заголовку среди всех статусов)."""
        if not self._resolve_settings().operations_center_enabled_effective:
            return []
        account_id = self._account_id(db, project_id)
        created: list[dict[str, Any]] = []
        for risk in open_risks:
            spec = _RISK_CATALOG.get(risk.risk_type)
            if spec is None:
                continue
            title = spec["action"]
            if repo.find_recommendation_by_title(db, project_id, title) is not None:
                continue
            rec = repo.create_recommendation(
                db,
                project_id=project_id,
                account_id=account_id,
                priority=spec["priority"],
                title=title,
                description=f"Ответ на риск: {risk.title}",
                reasoning=[risk.title],
                source_signals=[risk.risk_type, risk.source_module or "operations_center"],
                expected_impact={"health": "рост при снятии риска"},
            )
            created.append(repo.public_recommendation_view(rec))
        if created:
            self._write_audit(
                db,
                audit_actions.ACTION_OPERATIONS_RECOMMENDATION_CREATED,
                project_id,
                user_id,
                None,
                {"created": len(created)},
            )
        return created

    # ------------------------------------------------------------------ #
    # Объяснение                                                         #
    # ------------------------------------------------------------------ #

    def explain_operations_state(self, db: Session, project_id: int) -> dict[str, Any]:
        """Объяснение владельцу: почему здоровье бизнеса именно такое."""
        self._require_project(db, project_id)
        snapshot = repo.get_latest_snapshot(db, project_id)
        if snapshot is None:
            return {
                "project_id": project_id,
                "reasons": ["Запустите анализ (analyze), чтобы собрать операционный снапшот."],
            }
        metrics = snapshot.metrics or {}
        score = round(float(snapshot.health_score or 0), 1)
        reasons = [
            f"Health {score}/100 — статус «{snapshot.status}».",
            f"Рост: {round(float(metrics.get('growth', 0)), 1)}/100; "
            f"выручка: {round(float(metrics.get('revenue', 0)), 1)}/100; "
            f"исполнение: {round(float(metrics.get('execution', 0)), 1)}/100; "
            f"процессы: {round(float(metrics.get('workflow_progress', 0)), 1)}/100.",
        ]
        penalty = float(metrics.get("risk_penalty", 0) or 0)
        if penalty > 0:
            reasons.append(
                f"Риски снижают health на {round(penalty, 1)} ({snapshot.risk_count} открытых)."
            )
        open_risks = repo.list_active_risks(db, project_id)
        if open_risks:
            reasons.append("Главные риски: " + ", ".join(r.title for r in open_risks[:3]))
        return {"project_id": project_id, "reasons": reasons}

    # ------------------------------------------------------------------ #
    # Сбор сигналов                                                      #
    # ------------------------------------------------------------------ #

    def _collect_signals(self, db: Session, project_id: int, user_id: int | None) -> dict[str, Any]:
        exec_state = self._executive_state(db, project_id, user_id)
        rev = exec_state.get("revenue_state", {}) if isinstance(exec_state, dict) else {}
        content = exec_state.get("content_state", {}) if isinstance(exec_state, dict) else {}
        sales_state = exec_state.get("sales_state", {}) if isinstance(exec_state, dict) else {}
        prev = repo.get_latest_snapshot(db, project_id)
        prev_sales = (prev.sales_state or {}) if prev is not None else {}
        return {
            "business": {
                "business_health": exec_state.get("business_health", 0.0),
                "growth_score": exec_state.get("growth_score", 0.0),
                "best_platform": rev.get("best_platform", ""),
            },
            "growth": {
                "growth_score": exec_state.get("growth_score", 0.0),
                "opportunities": exec_state.get("opportunities", []),
                "risks": exec_state.get("risks", []),
            },
            "sales": {
                "revenue": rev.get("total_revenue", 0.0),
                "conversion": rev.get("conversion_rate", 0.0),
                "leads": sales_state.get("leads", 0),
            },
            "content": {
                "content_efficiency": content.get("content_efficiency", 0.0),
                "weak_areas": content.get("weak_areas", []),
            },
            "workflow": self._workflow_signals(db, project_id),
            "chief": self._chief_signals(db, project_id),
            "prev": {
                "revenue": prev_sales.get("revenue", None),
                "conversion": prev_sales.get("conversion", None),
            }
            if prev is not None
            else {},
        }

    def _components(self, signals: dict[str, Any]) -> dict[str, float]:
        biz = signals.get("business", {})
        sales = signals.get("sales", {})
        wf = signals.get("workflow", {})
        growth = float(biz.get("growth_score", 0.0) or 0.0)
        revenue = min(100.0, float(sales.get("revenue", 0.0) or 0.0) / 1000.0)
        if int(wf.get("active_workflows", 0) or 0) > 0:
            # без `or _NEUTRAL`: легитимные 0.0 (0% прогресса / нулевое здоровье) должны
            # оставаться 0.0, а не подменяться нейтральной базой.
            execution = float(wf.get("avg_health", _NEUTRAL))
            workflow_progress = float(wf.get("avg_progress", _NEUTRAL))
        else:
            execution = _NEUTRAL
            workflow_progress = _NEUTRAL
        return {
            "growth": round(growth, 1),
            "revenue": round(revenue, 1),
            "execution": round(execution, 1),
            "workflow_progress": round(workflow_progress, 1),
        }

    @staticmethod
    def _risk_penalty(open_risks: list[OperationsRisk]) -> float:
        penalty = sum(_RISK_PENALTY.get(r.severity, 5.0) for r in open_risks)
        return round(min(_RISK_PENALTY_CAP, penalty), 1)

    @staticmethod
    def _health_status(health_score: float) -> str:
        if health_score >= 70:
            return "healthy"
        if health_score >= 40:
            return "warning"
        return "critical"

    def _executive_state(self, db: Session, project_id: int, user_id: int | None) -> dict[str, Any]:
        """Состояние бизнеса (reuse AIExecutiveService.analyze_business_state, v0.7.0)."""
        try:
            from app.services.ai_executive_service import AIExecutiveService

            return AIExecutiveService(settings=self._resolve_settings()).analyze_business_state(
                db, project_id, user_id=user_id
            )
        except Exception as exc:  # noqa: BLE001 — снапшот не должен падать из-за нижнего слоя
            logger.warning("operations executive state failed: %s", type(exc).__name__)
            return {}

    def _workflow_signals(self, db: Session, project_id: int) -> dict[str, Any]:
        """Агрегированное здоровье активных процессов (reuse Workflow Manager, v0.7.2)."""
        empty = {
            "active_workflows": 0,
            "avg_progress": 0.0,
            "avg_health": 0.0,
            "open_blockers": 0,
            "stuck_steps": 0,
            "overdue_steps": 0,
        }
        try:
            from app.repositories import workflow_repository as wf_repo
            from app.services.ai_workflow_manager_service import AIWorkflowManagerService

            active = wf_repo.get_active_workflows(db, project_id)
            if not active:
                return empty
            svc = AIWorkflowManagerService(settings=self._resolve_settings())
            progresses: list[float] = []
            healths: list[float] = []
            blockers = stuck = overdue = 0
            for w in active:
                h = svc.analyze_workflow_health(db, w.id)
                progresses.append(float(h["progress_percent"]))
                healths.append(float(h["health_score"]))
                blockers += int(h["open_blockers"])
                stuck += int(h["stuck_steps"])
                overdue += int(h["overdue_steps"])
            return {
                "active_workflows": len(active),
                "avg_progress": round(sum(progresses) / len(progresses), 1),
                "avg_health": round(sum(healths) / len(healths), 1),
                "open_blockers": blockers,
                "stuck_steps": stuck,
                "overdue_steps": overdue,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("operations workflow signals failed: %s", type(exc).__name__)
            return empty

    def _chief_signals(self, db: Session, project_id: int) -> dict[str, Any]:
        """Сигналы AI Chief of Staff (открытые задачи, наличие брифинга; v0.7.1)."""
        try:
            from app.repositories import chief_of_staff_repository as chief_repo

            return {
                "open_tasks": len(chief_repo.list_open_tasks(db, project_id)),
                "has_briefing": chief_repo.get_latest_briefing(db, project_id) is not None,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("operations chief signals failed: %s", type(exc).__name__)
            return {"open_tasks": 0, "has_briefing": False}

    # ------------------------------------------------------------------ #
    # Инфраструктура                                                     #
    # ------------------------------------------------------------------ #

    def _require_project(self, db: Session, project_id: int) -> Any:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise AIOperationsControlError(f"Проект id={project_id} не найден")
        return project

    def _require_risk(self, db: Session, risk_id: int) -> OperationsRisk:
        risk = repo.get_risk(db, risk_id)
        if risk is None:
            raise AIOperationsControlError("Риск не найден")
        return risk

    def _require_recommendation(
        self, db: Session, recommendation_id: int
    ) -> OperationsRecommendation:
        rec = repo.get_recommendation(db, recommendation_id)
        if rec is None:
            raise AIOperationsControlError("Рекомендация не найдена")
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
            entity_type="operations_snapshot",
            entity_id=entity_id,
            metadata=metadata,
        )


def get_ai_operations_control_service() -> AIOperationsControlService:
    """DI-фабрика AI Operations Control Center."""
    return AIOperationsControlService()
