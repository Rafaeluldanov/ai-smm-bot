"""AIPilotFeedbackService — feedback loop пилота (v1.0.0).

Сохраняет решения владельца по AI-рекомендациям (accepted/rejected/modified) и их результат.
Feedback ТОЛЬКО сохраняется — НЕ меняет бизнес, НЕ выполняет рекомендацию, НЕ трогает KPI.

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- работает только при pilot_mode=true; feedback только фиксируется (никаких автодействий);
- секретов нет; бесплатно (0 units); изменения (feedback_created) → AuditLog.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import pilot_repository as repo
from app.services import audit_log_service as audit_actions
from app.services.ai_business_pilot_service import (
    AIBusinessPilotError,
    PilotModeDisabledError,
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.pilot_workspace import PilotWorkspace
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)


class AIPilotFeedbackService:
    """Feedback loop: решения владельца по рекомендациям (только сохранение)."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings

    def submit_feedback(
        self,
        db: Session,
        workspace_id: int,
        *,
        decision: str,
        recommendation_id: int | None = None,
        comment: str | None = None,
        result: str | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Сохранить решение владельца по рекомендации. НЕ выполняет и бизнес не меняет."""
        self._require_pilot_mode()
        from app.models.pilot_feedback import FEEDBACK_DECISIONS

        if decision not in FEEDBACK_DECISIONS:
            raise AIBusinessPilotError(f"Неизвестное решение: {decision}")
        workspace = self._require_workspace(db, workspace_id)
        feedback = repo.create_feedback(
            db,
            workspace_id=workspace.id,
            decision=decision,
            recommendation_id=recommendation_id,
            comment=comment,
            result=result,
        )
        self._write_audit(
            db,
            audit_actions.ACTION_PILOT_FEEDBACK_CREATED,
            workspace.account_id,
            user_id,
            feedback.id,
            {"decision": decision},
        )
        return repo.public_feedback_view(feedback)

    def accept_recommendation(
        self,
        db: Session,
        workspace_id: int,
        *,
        recommendation_id: int | None = None,
        comment: str | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Принять рекомендацию (только фиксация — НЕ применяет)."""
        return self.submit_feedback(
            db,
            workspace_id,
            decision="accepted",
            recommendation_id=recommendation_id,
            comment=comment,
            user_id=user_id,
        )

    def reject_recommendation(
        self,
        db: Session,
        workspace_id: int,
        *,
        recommendation_id: int | None = None,
        comment: str | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Отклонить рекомендацию (только фиксация)."""
        return self.submit_feedback(
            db,
            workspace_id,
            decision="rejected",
            recommendation_id=recommendation_id,
            comment=comment,
            user_id=user_id,
        )

    def record_result(
        self, db: Session, feedback_id: int, *, result: str, user_id: int | None = None
    ) -> dict[str, Any]:
        """Записать фактический результат к ранее сохранённому feedback (только фиксация)."""
        self._require_pilot_mode()
        feedback = repo.get_feedback(db, feedback_id)
        if feedback is None:
            raise AIBusinessPilotError("Feedback не найден")
        # Резолвим воркспейс для атрибуции аудита (запись результата — тоже мутация, её аудируем).
        workspace = repo.get_workspace(db, feedback.workspace_id)
        account_id = workspace.account_id if workspace is not None else None
        repo.update_feedback(db, feedback, result=result)
        self._write_audit(
            db,
            audit_actions.ACTION_PILOT_FEEDBACK_UPDATED,
            account_id,
            user_id,
            feedback.id,
            {"has_result": True},
        )
        return repo.public_feedback_view(feedback)

    def list_feedback(self, db: Session, workspace_id: int) -> list[dict[str, Any]]:
        """История обратной связи воркспейса."""
        self._require_pilot_mode()
        self._require_workspace(db, workspace_id)
        return [repo.public_feedback_view(f) for f in repo.list_feedback(db, workspace_id)]

    # ------------------------------------------------------------------ #
    # Внутреннее                                                         #
    # ------------------------------------------------------------------ #

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
            entity_type="pilot_feedback",
            entity_id=entity_id,
            metadata=metadata,
        )


def get_ai_pilot_feedback_service() -> AIPilotFeedbackService:
    """DI-фабрика AI Pilot Feedback."""
    return AIPilotFeedbackService()
