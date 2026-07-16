"""AIBusinessPilotScenarioService — pilot-прогон AI-цепочки (v0.9.1).

Запускает всю AI-цепочку (Decision → … → Governance) на ИЗОЛИРОВАННОМ pilot-проекте, переиспользуя
E2E-конвейер v0.9.0. Дополнительно фиксирует состояние бизнеса из профиля (Performance snapshot) для
advisory-health. Только advisory: НЕ execute, НЕ workflow-conversion, НЕ внешних действий.

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- работает только при pilot_mode=true; все вызываемые слои — advisory (v0.9.0 pipeline: без publish/
  workflow/CRM/сообщений); НЕ создаёт платежей;
- прогон на ОТДЕЛЬНОМ pilot-проекте (slug pilot-ws-<id>); падение этапа/сохранения не роняет запрос;
- секретов нет; бесплатно (0 units); изменения (scenario_started) → AuditLog.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import pilot_repository as repo
from app.repositories import project_repository
from app.services import audit_log_service as audit_actions
from app.services.ai_business_pilot_service import (
    AIBusinessPilotError,
    PilotModeDisabledError,
    pilot_project_slug,
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.pilot_workspace import PilotWorkspace
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)


class AIBusinessPilotScenarioService:
    """Pilot-прогон AI-цепочки (переиспользует v0.9.0 pipeline)."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings

    def run_growth_pilot(
        self, db: Session, workspace_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Прогнать growth-пилот: Decision → … → Governance на pilot-проекте (advisory)."""
        self._require_pilot_mode()
        workspace = self._require_workspace(db, workspace_id)
        self._write_audit(
            db,
            audit_actions.ACTION_PILOT_SCENARIO_STARTED,
            workspace.account_id,
            user_id,
            workspace.id,
            {"scenario": "growth"},
        )

        try:
            project_id = self._pilot_project(db, workspace)
            stages = self._run_pipeline(db, project_id, workspace.account_id)
            self._seed_profile_state(db, project_id, workspace)
            passed = sum(1 for s in stages if s.get("status") == "pass")
            produced = sum(1 for s in stages if s.get("produced"))
            total = len(stages)
            score = round((0.7 * passed + 0.3 * produced) / total * 100, 1) if total else 0.0
            status = "completed"
        except Exception as exc:  # noqa: BLE001 — прогон не должен ронять запрос
            logger.warning("pilot scenario run failed: %s", type(exc).__name__)
            db.rollback()
            project_id = None
            stages = []
            passed = produced = total = 0
            score = 0.0
            status = "failed"

        return {
            "workspace_id": workspace.id,
            "project_id": project_id,
            "scenario": "growth",
            "status": status,
            "stages": stages,
            "passed": passed,
            "produced": produced,
            "total": total,
            "score": score,
        }

    # ------------------------------------------------------------------ #
    # Внутреннее                                                         #
    # ------------------------------------------------------------------ #

    def _run_pipeline(
        self, db: Session, project_id: int, account_id: int | None
    ) -> list[dict[str, Any]]:
        """Переиспользовать E2E-конвейер v0.9.0 (все advisory-слои, каждый в try/except)."""
        from app.services.ai_business_os_scenario_service import AIBusinessOSScenarioService

        runner = AIBusinessOSScenarioService(settings=self._resolve_settings())
        return runner._run_pipeline(db, project_id, account_id, "growth")

    def _pilot_project(self, db: Session, workspace: PilotWorkspace) -> int:
        """Резолвить/создать ИЗОЛИРОВАННЫЙ pilot-проект (детерминированный slug)."""
        from app.schemas.project import ProjectCreate

        slug = pilot_project_slug(workspace.id)
        project = project_repository.get_project_by_slug(db, slug)
        if project is not None:
            # slug глобально уникален: совпал с проектом ЧУЖОГО аккаунта — отказ (не пишем туда).
            if project.account_id != workspace.account_id:
                raise AIBusinessPilotError("Slug pilot-проекта занят другим аккаунтом")
            return project.id
        project = project_repository.create_project(
            db, ProjectCreate(name=f"[PILOT] {workspace.company_name}"[:255], slug=slug)
        )
        project.account_id = workspace.account_id
        db.commit()
        db.refresh(project)
        return project.id

    def _seed_profile_state(self, db: Session, project_id: int, workspace: PilotWorkspace) -> None:
        """Зафиксировать текущее состояние бизнеса из профиля (Performance snapshot) для health."""
        profile = repo.get_profile(db, workspace.id)
        if profile is None:
            return
        try:
            from app.repositories import performance_repository as perf_repo

            current = float(profile.current_revenue or 0.0)
            target = float(profile.target_revenue or 0.0)
            ratio = current / target if target > 0 else 1.0
            status = "healthy" if ratio >= 0.9 else ("warning" if ratio >= 0.6 else "critical")
            score = round(min(100.0, max(0.0, ratio * 100.0)), 1)
            snapshot = perf_repo.create_snapshot(
                db,
                project_id=project_id,
                account_id=workspace.account_id,
                status=status,
                performance_score=score,
                target_state={"revenue": target},
                actual_state={"revenue": current},
            )
            if status != "healthy":
                perf_repo.create_deviation(
                    db,
                    snapshot_id=snapshot.id,
                    metric="revenue",
                    title=f"Выручка {current:.0f} из целевых {target:.0f}",
                    impact="high" if status == "warning" else "critical",
                )
        except Exception as exc:  # noqa: BLE001 — сидирование не должно ронять прогон
            logger.warning("pilot seed profile state failed: %s", type(exc).__name__)
            db.rollback()

    def _require_pilot_mode(self) -> None:
        if not self._resolve_settings().pilot_mode_effective:
            raise PilotModeDisabledError("PILOT-режим выключен (pilot_mode=false)")

    def _require_workspace(self, db: Session, workspace_id: int) -> PilotWorkspace:
        workspace = repo.get_workspace(db, workspace_id)
        if workspace is None:
            raise AIBusinessPilotError("Pilot-воркспейс не найден")
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
            entity_type="pilot_workspace",
            entity_id=entity_id,
            metadata=metadata,
        )


def get_ai_business_pilot_scenario_service() -> AIBusinessPilotScenarioService:
    """DI-фабрика AI Business Pilot Scenario runner."""
    return AIBusinessPilotScenarioService()
