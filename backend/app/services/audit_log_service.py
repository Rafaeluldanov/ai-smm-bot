"""Сервис аудит-лога SaaS: запись действий и чтение по аккаунту.

Аудит НИКОГДА не роняет основное действие: при ``AUDIT_LOG_ENABLED=false`` запись
пропускается, а исключения при записи проглатываются (логируются в приложении, но не
пробрасываются). Метаданные санитизируются через ``core.redaction`` — секреты в аудит
не попадают.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.core.redaction import sanitize_metadata
from app.models.audit_log import AuditLogEntry
from app.repositories import audit_log_repository

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)

# Действия аудита (стабильные строковые коды).
ACTION_USER_REGISTERED = "user.registered"
ACTION_USER_LOGIN = "user.login"
ACTION_USER_LOGOUT = "user.logout"
ACTION_USER_REFRESH = "user.refresh"
ACTION_USER_SESSION_REVOKED = "user.session.revoked"
ACTION_USER_LOGOUT_ALL = "user.logout_all"
ACTION_PROJECT_CREATED = "project.created"
ACTION_PROJECT_UPDATED = "project.updated"
ACTION_PLATFORM_CONNECTED = "platform.connected"
ACTION_PLATFORM_SECRET_UPDATED = "platform.secret.updated"
ACTION_SCHEDULE_CREATED = "schedule.created"
ACTION_SCHEDULE_UPDATED = "schedule.updated"
ACTION_SCHEDULE_DELETED = "schedule.deleted"
ACTION_ANALYTICS_RUN = "analytics.run"
ACTION_INVOICE_CREATED = "billing.invoice.created"
ACTION_INVOICE_PAID = "billing.invoice.paid"
ACTION_INVOICE_FAILED = "billing.invoice.failed"
ACTION_INVOICE_CANCELED = "billing.invoice.canceled"
ACTION_INVOICE_EXPIRED = "billing.invoice.expired"
ACTION_BALANCE_DEBITED = "billing.balance.debited"
ACTION_BALANCE_CREDITED = "billing.balance.credited"
ACTION_OAUTH_CONNECTED = "oauth.connected"
ACTION_OAUTH_FAILED = "oauth.failed"


class AuditLogService:
    """Запись/чтение аудита действий (безопасно, без секретов)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings

    def _enabled(self) -> bool:
        settings = self._settings
        if settings is None:
            from app.config import get_settings

            settings = get_settings()
        return bool(settings.audit_log_enabled)

    @staticmethod
    def sanitize_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
        """Очистить метаданные от секретов (через core.redaction)."""
        if not metadata:
            return {}
        cleaned = sanitize_metadata(metadata)
        return cleaned if isinstance(cleaned, dict) else {}

    def record(
        self,
        db: Session,
        action: str,
        *,
        account_id: int | None = None,
        user_id: int | None = None,
        project_id: int | None = None,
        entity_type: str = "",
        entity_id: str | int | None = None,
        metadata: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLogEntry | None:
        """Записать событие аудита. Никогда не роняет основное действие."""
        if not self._enabled():
            return None
        try:
            return audit_log_repository.create_entry(
                db,
                account_id=account_id,
                user_id=user_id,
                project_id=project_id,
                action=action,
                entity_type=entity_type,
                entity_id=None if entity_id is None else str(entity_id),
                ip_address=ip_address,
                user_agent=(user_agent or "")[:512] or None,
                entry_metadata=self.sanitize_metadata(metadata),
            )
        except Exception:  # noqa: BLE001 — аудит не должен ронять основное действие
            logger.warning("audit-log record failed for action=%s", action, exc_info=False)
            with contextlib.suppress(Exception):
                db.rollback()
            return None

    def list_for_account(
        self, db: Session, account_id: int, limit: int = 100, offset: int = 0
    ) -> list[AuditLogEntry]:
        """Записи аудита аккаунта (свежие первыми)."""
        return audit_log_repository.list_for_account(db, account_id, limit, offset)


def get_audit_log_service() -> AuditLogService:
    """DI-фабрика сервиса аудита."""
    return AuditLogService()
