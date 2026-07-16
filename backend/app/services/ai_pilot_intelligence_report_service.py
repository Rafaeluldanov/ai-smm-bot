"""AIPilotIntelligenceReportService — AI Business Intelligence Report (v1.0.0).

Формирует «AI Business Intelligence Report» из контекста компании и health: компания, текущее
состояние, сильные/слабые стороны, риски, возможности, AI-рекомендации. ТОЛЬКО аналитика уже
собранных данных — ничего не выполняет и бизнес не меняет.

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
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.pilot_workspace import PilotWorkspace
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)


class AIPilotIntelligenceReportService:
    """Формирование AI Business Intelligence Report (read-only, advisory)."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings

    def generate_intelligence_report(
        self, db: Session, workspace_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Собрать intelligence-отчёт: компания/состояние/SWOT/AI-рекомендации."""
        self._require_pilot_mode()
        workspace = self._require_workspace(db, workspace_id)
        settings = self._resolve_settings()
        context = AIBusinessContextService(settings=settings).analyze_company_context(
            db, workspace_id
        )
        health = AIBusinessPilotService(settings=settings).get_business_health(db, workspace_id)
        profile = repo.get_profile(db, workspace.id)

        risks = context.get("risks", [])
        opportunities = context.get("opportunities", [])
        current_state = f"Health {health.get('score', 0.0)}/100" + (
            f"; главная проблема: {risks[0]}" if risks else "; критичных проблем нет"
        )
        report = {
            "workspace_id": workspace.id,
            "title": f"AI Business Intelligence Report — {workspace.company_name}",
            "company": {
                "name": workspace.company_name,
                "industry": workspace.industry,
                "current_revenue": float(profile.current_revenue or 0.0)
                if profile is not None
                else 0.0,
                "target_revenue": float(profile.target_revenue or 0.0)
                if profile is not None
                else 0.0,
            },
            "current_state": current_state,
            "strengths": context.get("strengths", []),
            "weaknesses": context.get("weaknesses", []),
            "risks": risks,
            "opportunities": opportunities,
            "ai_recommendations": self._recommendations(risks, opportunities),
            "has_data": context.get("has_data", False),
        }
        self._write_audit(
            db,
            audit_actions.ACTION_PILOT_INTELLIGENCE_GENERATED,
            workspace.account_id,
            user_id,
            workspace.id,
            {"health_score": health.get("score", 0.0)},
        )
        return report

    # ------------------------------------------------------------------ #
    # Внутреннее                                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _recommendations(risks: list[str], opportunities: list[str]) -> list[str]:
        """AI-рекомендации (advisory: применяет владелец вручную)."""
        recommendations: list[str] = []
        if risks:
            recommendations.append(f"Приоритет: снять риск «{risks[0]}».")
        if opportunities:
            recommendations.append(f"Использовать возможность: {opportunities[0]}.")
        recommendations.append("Провести review улучшений и приоритизировать оптимизации.")
        recommendations.append(
            "Все рекомендации — advisory: применяет владелец вручную, бизнес не меняется."
        )
        return recommendations

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


def get_ai_pilot_intelligence_report_service() -> AIPilotIntelligenceReportService:
    """DI-фабрика AI Pilot Intelligence Report."""
    return AIPilotIntelligenceReportService()
