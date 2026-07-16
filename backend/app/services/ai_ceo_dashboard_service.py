"""AICEODashboardService — CEO Dashboard пилота (v0.9.1).

Собирает «AI Business Command Center»: business score, текущая ситуация, риски, возможности,
действия на сегодня и прогноз. ТОЛЬКО чтение собранных данных (Performance/Operations/Forecast
через pilot health) — ничего не выполняет и бизнес не меняет.

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- работает только при pilot_mode=true; всё advisory/read-only; внешних действий/мутаций бизнеса нет;
- секретов нет; бесплатно (0 units); формирование → AuditLog.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import pilot_repository as repo
from app.services import audit_log_service as audit_actions
from app.services.ai_business_pilot_service import (
    AIBusinessPilotError,
    AIBusinessPilotService,
    PilotModeDisabledError,
    resolve_pilot_project,
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.pilot_workspace import PilotWorkspace
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)


class AICEODashboardService:
    """Формирование CEO Dashboard из pilot health + forecast."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings

    def generate_dashboard(
        self, db: Session, workspace_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Собрать CEO Dashboard: score / ситуация / риски / возможности / действия / прогноз."""
        self._require_pilot_mode()
        workspace = self._require_workspace(db, workspace_id)
        health = self._pilot_service().get_business_health(db, workspace_id)
        forecast_block = self._forecast_block(db, workspace)
        risks = health.get("risks", [])
        opportunities = health.get("opportunities", [])
        current_state = risks[0] if risks else "Бизнес в пределах нормы — критичных проблем нет"
        dashboard = {
            "workspace_id": workspace.id,
            "company_name": workspace.company_name,
            "business_score": health.get("score", 0.0),
            "current_state": current_state,
            "risks": risks,
            "opportunities": opportunities,
            "today_actions": self._today_actions(opportunities, health.get("has_data", False)),
            "forecast": forecast_block,
            "has_data": health.get("has_data", False),
        }
        self._write_audit(
            db,
            audit_actions.ACTION_PILOT_DASHBOARD_GENERATED,
            workspace.account_id,
            user_id,
            workspace.id,
            {"business_score": dashboard["business_score"]},
        )
        return dashboard

    # ------------------------------------------------------------------ #
    # Внутреннее                                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _today_actions(opportunities: list[str], has_data: bool) -> list[str]:
        """Что делать сегодня (advisory): из возможностей, иначе осмысленный фолбэк."""
        if opportunities:
            return opportunities[:3]
        if has_data:
            return ["Провести review улучшений и приоритизировать оптимизации (advisory)"]
        return ["Запустите pilot-анализ, чтобы получить рекомендации"]

    def _forecast_block(self, db: Session, workspace: PilotWorkspace) -> dict[str, Any]:
        """Блок прогноза из последнего Business Forecast pilot-проекта (read-only, tenant-safe)."""
        project = resolve_pilot_project(db, workspace)
        if project is None:
            return {"available": False}
        try:
            from app.repositories import business_forecast_repository as fc_repo

            forecast = fc_repo.get_latest_forecast(db, project.id)
            if forecast is None:
                return {"available": False}
            return {
                "available": True,
                "horizon": forecast.horizon,
                "confidence_score": round(float(forecast.confidence_score or 0.0), 1),
                "risk_level": forecast.risk_level,
                "forecast_state": dict(forecast.forecast_state or {}),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("ceo dashboard forecast failed: %s", type(exc).__name__)
            return {"available": False}

    def _pilot_service(self) -> AIBusinessPilotService:
        return AIBusinessPilotService(settings=self._resolve_settings())

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


def get_ai_ceo_dashboard_service() -> AICEODashboardService:
    """DI-фабрика AI CEO Dashboard."""
    return AICEODashboardService()
