"""AIOptimizationGovernanceService — AI Optimization Governance Engine (v0.8.2).

Добавляет управление портфелем улучшений поверх Autonomous Optimization (v0.8.1): создаёт
governance-записи, ведёт review/approval flow, назначает владельцев, считает portfolio-метрики и
отслеживает impact по результатам экспериментов.

Поток: **Optimization Item → Governance Review → Approval → Ownership → Impact Tracking**.

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- это governance/управляющий слой: только управляет статусами, владельцами и impact;
- НЕ применяет улучшения, НЕ запускает эксперименты, НЕ меняет бизнес/KPI/CRM/бюджет, НЕ выполняет
  задачи; approve/reject меняют ТОЛЬКО статусы governance;
- назначение владельца — ТОЛЬКО участнику аккаунта (FAIL CLOSED: сбой проверки → отказ);
- ВЕСЬ сбор смежных слоёв (Optimization / Continuous Improvement) — READ-ONLY в try/except;
- строго per-project; секретов нет; бесплатно (0 units);
- каждое изменение (governance.created/review_created/approved/rejected/owner_assigned/
  impact_updated) → AuditLog.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import optimization_governance_repository as repo
from app.repositories import optimization_repository as opt_repo
from app.repositories import project_repository
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.optimization_governance import OptimizationGovernance
    from app.models.optimization_item import OptimizationItem
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

# Итог валидации эксперимента → статус impact.
_VALIDATION_TO_IMPACT: dict[str, str] = {
    "success": "positive",
    "failure": "negative",
    "inconclusive": "neutral",
}


class AIOptimizationGovernanceError(Exception):
    """Ошибка Governance (нет проекта/governance; владелец без доступа) — API → 400/404."""


class AIOptimizationGovernanceService:
    """AI governance портфеля: optimization → review → approval → ownership → impact."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Цикл governance                                                    #
    # ------------------------------------------------------------------ #

    def run_governance_cycle(
        self, db: Session, project_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Завести governance для оптимизаций проекта (идемпотентно). НЕ утверждает/не запускает."""
        self._require_project(db, project_id)
        try:
            optimizations = opt_repo.list_optimizations(db, project_id)
        except Exception as exc:  # noqa: BLE001 — падение соседа не должно ронять цикл
            logger.warning("governance optimization read failed: %s", type(exc).__name__)
            optimizations = []
        created: list[dict[str, Any]] = []
        for optimization in optimizations:
            view = self.create_governance(db, project_id, optimization, user_id)
            if view is not None:
                created.append(view)
        # Impact tracking: governance с завершённым экспериментом и без impact (идемпотентно).
        for governance in repo.list_governances(db, project_id):
            if repo.get_latest_impact(db, governance.id) is not None:
                continue
            try:
                experiments = opt_repo.list_experiments(db, governance.optimization_id)
            except Exception as exc:  # noqa: BLE001 — read-only соседа не роняет цикл
                logger.warning("governance cycle experiments read failed: %s", type(exc).__name__)
                continue
            if any(e.status == "completed" for e in experiments):
                self.track_impact(db, governance.id, user_id)
        # Единожды считаем список и метрики, переиспользуем в explain (без дублей запросов).
        governances = repo.list_governances(db, project_id)
        metrics = repo.get_portfolio_metrics(db, project_id)
        return {
            "created": created,
            "governances": [repo.public_governance_view(g) for g in governances],
            "portfolio": metrics,
            "insights": self.explain_governance(
                db, project_id, metrics=metrics, governances=governances
            )["insights"],
        }

    def create_governance(
        self,
        db: Session,
        project_id: int,
        optimization: OptimizationItem,
        user_id: int | None = None,
    ) -> dict[str, Any] | None:
        """Создать OptimizationGovernance из OptimizationItem (идемпотентно)."""
        existing = repo.list_governances_by_optimization(db, project_id, optimization.id)
        if existing:
            return None  # уже под governance — не дублируем
        account_id = self._account_id(db, project_id)
        governance = repo.create_governance(
            db,
            project_id=project_id,
            account_id=account_id,
            optimization_id=optimization.id,
            priority=optimization.priority,
            status="identified",
            approval_status="pending",
        )
        self._write_audit(
            db,
            audit_actions.ACTION_GOVERNANCE_CREATED,
            project_id,
            user_id,
            governance.id,
            {"optimization_id": optimization.id, "priority": optimization.priority},
        )
        return repo.public_governance_view(governance)

    # ------------------------------------------------------------------ #
    # Review / approval                                                  #
    # ------------------------------------------------------------------ #

    def submit_review(
        self,
        db: Session,
        governance_id: int,
        *,
        reviewer_user_id: int | None = None,
        decision: str = "comment",
        comment: str | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Создать GovernanceReview; статус identified → review. НЕ утверждает."""
        governance = self._require_governance(db, governance_id)
        review = repo.create_review(
            db,
            governance_id=governance.id,
            reviewer_user_id=reviewer_user_id,
            decision=decision,
            comment=comment,
        )
        updates: dict[str, Any] = {}
        if governance.status == "identified":
            updates["status"] = "review"
        if comment:
            updates["review_notes"] = comment
        if updates:
            repo.update_governance(db, governance, **updates)
        self._write_audit(
            db,
            audit_actions.ACTION_GOVERNANCE_REVIEW_CREATED,
            governance.project_id,
            user_id,
            review.id,
            {"decision": decision},
            entity_type="governance_review",
        )
        return repo.public_review_view(review)

    def approve_optimization(
        self, db: Session, governance_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Согласовать: approval_status pending → approved (status → approved). НЕ запускает."""
        governance = self._require_governance(db, governance_id)
        if governance.approval_status != "pending":
            raise AIOptimizationGovernanceError("Governance уже обработан")
        repo.approve(db, governance)
        self._write_audit(
            db,
            audit_actions.ACTION_GOVERNANCE_APPROVED,
            governance.project_id,
            user_id,
            governance.id,
            {},
        )
        return repo.public_governance_view(governance)

    def reject_optimization(
        self, db: Session, governance_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Отклонить: approval_status → rejected (status → rejected)."""
        governance = self._require_governance(db, governance_id)
        if governance.approval_status != "pending":
            raise AIOptimizationGovernanceError("Governance уже обработан")
        repo.reject(db, governance)
        self._write_audit(
            db,
            audit_actions.ACTION_GOVERNANCE_REJECTED,
            governance.project_id,
            user_id,
            governance.id,
            {},
        )
        return repo.public_governance_view(governance)

    # ------------------------------------------------------------------ #
    # Ownership                                                          #
    # ------------------------------------------------------------------ #

    def assign_owner(
        self,
        db: Session,
        governance_id: int,
        owner_user_id: int,
        *,
        role: str = "owner",
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Назначить владельца governance (ТОЛЬКО участнику аккаунта, FAIL CLOSED)."""
        governance = self._require_governance(db, governance_id)
        self._require_account_member(db, governance, owner_user_id)
        assignment = repo.assign_owner(db, governance, owner_user_id, role=role)
        # Одобренная запись с назначенным владельцем переходит в работу (approved → active).
        if governance.status == "approved":
            repo.update_governance(db, governance, status="active")
        self._write_audit(
            db,
            audit_actions.ACTION_GOVERNANCE_OWNER_ASSIGNED,
            governance.project_id,
            user_id,
            assignment.id,
            {"owner_user_id": owner_user_id, "role": role},
            entity_type="optimization_owner_assignment",
        )
        return repo.public_assignment_view(assignment)

    # ------------------------------------------------------------------ #
    # Impact                                                             #
    # ------------------------------------------------------------------ #

    def track_impact(
        self, db: Session, governance_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Отследить impact по результату эксперимента (read-only). Создать OptimizationImpact."""
        governance = self._require_governance(db, governance_id)
        experiment_id: int | None = None
        status = "unknown"
        impact_score = 0.0
        expected: dict[str, Any] = {}
        actual: dict[str, Any] = {}
        try:
            optimization = opt_repo.get_optimization(db, governance.optimization_id)
            experiments = opt_repo.list_experiments(db, governance.optimization_id)
            completed = [e for e in experiments if e.status == "completed"]
            if completed:
                experiment = completed[0]
                experiment_id = experiment.id
                result = opt_repo.get_latest_result(db, experiment.id)
                if result is not None:
                    status = _VALIDATION_TO_IMPACT.get(result.validation_result, "neutral")
                    base = float(optimization.optimization_score or 0.0) if optimization else 0.0
                    if status == "positive":
                        impact_score = base
                    elif status == "neutral":
                        impact_score = round(base / 2.0, 1)
                    else:
                        impact_score = 0.0
                    expected = {"metric": experiment.metric, "target": experiment.target_value}
                    actual = {
                        "actual": result.actual_value,
                        "difference": result.difference,
                        "validation": result.validation_result,
                    }
                else:
                    status = "measuring"
            elif experiments:
                status = "measuring"
        except Exception as exc:  # noqa: BLE001 — read-only соседа не должен ронять трекинг
            logger.warning("governance impact read failed: %s", type(exc).__name__)

        impact = repo.create_impact(
            db,
            governance_id=governance.id,
            experiment_id=experiment_id,
            status=status,
            expected_impact=expected,
            actual_impact=actual,
            impact_score=impact_score,
        )
        # Измеренный impact завершает активную governance-запись (active → completed).
        if governance.status == "active" and status in ("positive", "negative", "neutral"):
            repo.update_governance(db, governance, status="completed")
        self._write_audit(
            db,
            audit_actions.ACTION_GOVERNANCE_IMPACT_UPDATED,
            governance.project_id,
            user_id,
            impact.id,
            {"status": status},
            entity_type="optimization_impact",
        )
        return repo.public_impact_view(impact)

    # ------------------------------------------------------------------ #
    # Portfolio / explain                                                #
    # ------------------------------------------------------------------ #

    def calculate_portfolio_metrics(self, db: Session, project_id: int) -> dict[str, Any]:
        """Метрики портфеля: total/approved/active/completed/impact."""
        self._require_project(db, project_id)
        return repo.get_portfolio_metrics(db, project_id)

    def explain_governance(
        self,
        db: Session,
        project_id: int,
        *,
        metrics: dict[str, Any] | None = None,
        governances: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Объяснить владельцу, почему улучшение прошло approval.

        Принимает предвычисленные metrics/governances (переиспользование), иначе читает сам.
        """
        if metrics is None:
            metrics = repo.get_portfolio_metrics(db, project_id)
        if governances is None:
            governances = repo.list_governances(db, project_id)
        approved = [g for g in governances if g.approval_status == "approved"]
        insights: list[str] = [
            f"Портфель: всего {metrics['total']}, одобрено {metrics['approved']}, "
            f"активно {metrics['active']}, завершено {metrics['completed']}; "
            f"средний impact {metrics['avg_impact_score']}."
        ]
        if approved:
            top = approved[0]
            owner = "владелец назначен" if top.owner_user_id else "владелец не назначен"
            insights.append(
                f"Улучшение #{top.optimization_id} прошло approval "
                f"(приоритет {top.priority}, {owner})."
            )
        else:
            insights.append("Одобренных улучшений пока нет — проведите review и approval.")
        insights.append(
            "Это управление портфелем; улучшения НЕ применяются, бизнес/KPI не меняются."
        )
        return {"project_id": project_id, "insights": insights}

    # ------------------------------------------------------------------ #
    # Чтение                                                             #
    # ------------------------------------------------------------------ #

    def get_governances(
        self,
        db: Session,
        project_id: int,
        *,
        status: str | None = None,
        approval_status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Governance-записи проекта."""
        self._require_project(db, project_id)
        return [
            repo.public_governance_view(g)
            for g in repo.list_governances(
                db, project_id, status=status, approval_status=approval_status
            )
        ]

    def get_governance_detail(self, db: Session, governance_id: int) -> dict[str, Any]:
        """Governance + ревью + impacts + история назначений."""
        governance = self._require_governance(db, governance_id)
        return {
            "governance": repo.public_governance_view(governance),
            "reviews": [repo.public_review_view(r) for r in repo.list_reviews(db, governance.id)],
            "impacts": [repo.public_impact_view(i) for i in repo.list_impacts(db, governance.id)],
            "assignments": [
                repo.public_assignment_view(a)
                for a in repo.list_owner_assignments(db, governance.id)
            ],
        }

    def get_portfolio(self, db: Session, project_id: int) -> dict[str, Any]:
        """Метрики портфеля + выводы."""
        self._require_project(db, project_id)
        return {
            "metrics": repo.get_portfolio_metrics(db, project_id),
            "insights": self.explain_governance(db, project_id)["insights"],
        }

    # ------------------------------------------------------------------ #
    # Внутреннее                                                         #
    # ------------------------------------------------------------------ #

    def _require_project(self, db: Session, project_id: int) -> Any:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise AIOptimizationGovernanceError(f"Проект id={project_id} не найден")
        return project

    def _require_governance(self, db: Session, governance_id: int) -> OptimizationGovernance:
        governance = repo.get_governance(db, governance_id)
        if governance is None:
            raise AIOptimizationGovernanceError("Governance не найден")
        return governance

    def _require_account_member(
        self, db: Session, governance: OptimizationGovernance, owner_user_id: int
    ) -> None:
        """Владелец должен иметь доступ к аккаунту проекта (tenant isolation).

        FAIL CLOSED: любой сбой самой проверки — отказ (назначение НЕ проходит), а не пропуск;
        governance без аккаунта (account_id=None) → тоже отказ (нет аккаунта для проверки владения).
        """
        from app.repositories import user_repository
        from app.services import saas_security_service as security

        account_id = governance.account_id
        if account_id is None:
            raise AIOptimizationGovernanceError("Нет аккаунта для проверки доступа владельца")
        try:
            user = user_repository.get_user_by_id(db, owner_user_id)
            allowed = user is not None and security.user_can_access_account(db, user, account_id)
        except Exception as exc:  # noqa: BLE001 — сбой проверки доступа → fail closed
            logger.warning("governance owner check failed: %s", type(exc).__name__)
            raise AIOptimizationGovernanceError("Не удалось проверить доступ владельца") from exc
        if not allowed:
            raise AIOptimizationGovernanceError("Владелец не имеет доступа к проекту")

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
        entity_type: str = "optimization_governance",
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


def get_ai_optimization_governance_service() -> AIOptimizationGovernanceService:
    """DI-фабрика AI Optimization Governance."""
    return AIOptimizationGovernanceService()
