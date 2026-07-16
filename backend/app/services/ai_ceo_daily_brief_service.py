"""AICEODailyBriefService — CEO Daily Brief (v1.0.0).

Формирует ежедневную сводку для владельца: health score, главное событие, риски, возможности,
действия на сегодня и прогноз. ТОЛЬКО чтение уже собранных данных — ничего не выполняет и бизнес не
меняет.

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- работает только при pilot_mode=true; всё advisory/read-only; внешних действий/мутаций бизнеса нет;
- секретов нет; бесплатно (0 units); формирование → AuditLog.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import pilot_repository as repo
from app.services import audit_log_service as audit_actions
from app.services.ai_business_context_service import AIBusinessContextService
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


class AICEODailyBriefService:
    """Формирование CEO Daily Brief (read-only, advisory)."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings

    def generate_daily_brief(
        self, db: Session, workspace_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Собрать Daily Brief: health/главное событие/риски/возможности/действия/прогноз."""
        self._require_pilot_mode()
        workspace = self._require_workspace(db, workspace_id)
        settings = self._resolve_settings()
        health = AIBusinessPilotService(settings=settings).get_business_health(db, workspace_id)
        context = AIBusinessContextService(settings=settings).analyze_company_context(
            db, workspace_id
        )
        risks = context.get("risks", [])
        opportunities = context.get("opportunities", [])
        main_event = risks[0] if risks else "Бизнес стабилен — критичных событий нет"
        today_actions = opportunities[:3] or ["Контролировать KPI и подтвердить приоритеты дня"]
        brief = {
            "workspace_id": workspace.id,
            "greeting": "Доброе утро.",
            "company_name": workspace.company_name,
            "health_score": health.get("score", 0.0),
            "main_event": main_event,
            "risks": risks,
            "opportunities": opportunities,
            "today_actions": today_actions,
            "forecast": self._forecast_block(db, workspace),
            "has_data": health.get("has_data", False),
        }
        self._write_audit(
            db,
            audit_actions.ACTION_PILOT_DAILY_BRIEF_GENERATED,
            workspace.account_id,
            user_id,
            workspace.id,
            {"health_score": brief["health_score"]},
        )
        return brief

    # ------------------------------------------------------------------ #
    # Внутреннее                                                         #
    # ------------------------------------------------------------------ #

    def _forecast_block(self, db: Session, workspace: PilotWorkspace) -> dict[str, Any]:
        """Прогноз из последнего Business Forecast pilot-проекта (read-only, tenant-safe)."""
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
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("daily brief forecast failed: %s", type(exc).__name__)
            return {"available": False}

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


def get_ai_ceo_daily_brief_service() -> AICEODailyBriefService:
    """DI-фабрика AI CEO Daily Brief."""
    return AICEODailyBriefService()
