"""Сервис подавления доставки (suppression) — v0.5.2.

Если внешняя доставка по каналу многократно падает, канал/адрес временно подавляется. Сырой
адрес НЕ хранится — только SHA-256 hash. Успешная доставка сбрасывает счётчик и снимает
подавление. Внешних вызовов нет.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.repositories import notification_safety_repository as safety_repo
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:
    from app.config import Settings
    from app.models.notification_suppression import NotificationSuppression
    from app.services.audit_log_service import AuditLogService


def hash_destination(destination: str | None) -> str | None:
    """SHA-256 hash адреса доставки (без хранения сырого значения)."""
    if not destination:
        return None
    return hashlib.sha256(destination.strip().lower().encode("utf-8")).hexdigest()[:64]


class NotificationSuppressionError(Exception):
    """Ошибка подавления (нет доступа/сущности) — API → 400/404."""


class NotificationSuppressionService:
    """Подавление доставки по каналу/адресу при ошибках + ручной сброс."""

    def __init__(
        self, audit_service: AuditLogService | None = None, settings: Settings | None = None
    ) -> None:
        self._audit = audit_service
        self._settings = settings

    def is_suppressed(
        self,
        db: Session,
        user_id: int | None,
        channel: str,
        provider: str | None = None,
        destination: str | None = None,
        project_id: int | None = None,  # noqa: ARG002 — единый интерфейс
    ) -> NotificationSuppression | None:
        """Активное подавление канала/адреса (или None)."""
        if not self._enabled():
            return None
        return safety_repo.is_suppressed(
            db, user_id, channel, provider, hash_destination(destination)
        )

    def record_delivery_failure(
        self,
        db: Session,
        user_id: int | None,
        channel: str,
        provider: str | None = None,
        destination: str | None = None,
        account_id: int | None = None,
        project_id: int | None = None,
    ) -> dict[str, Any]:
        """Зафиксировать ошибку доставки; при достижении порога — активировать подавление."""
        if not self._enabled():
            return {"enabled": False, "suppressed": False}
        row, activated = safety_repo.record_failure(
            db,
            user_id=user_id,
            channel=channel,
            threshold=self._threshold(),
            ttl_seconds=self._ttl_seconds(),
            provider=provider,
            destination_hash=hash_destination(destination),
            account_id=account_id,
            project_id=project_id,
        )
        if activated:
            self._write_audit(
                db,
                audit_actions.ACTION_NOTIFICATION_SUPPRESSION_CREATED,
                row,
                {"suppression_id": row.id, "channel": channel, "reason": row.reason},
            )
        return {
            "enabled": True,
            "suppressed": row.status == "active",
            "failure_count": row.failure_count,
            "suppression_id": row.id,
        }

    def record_delivery_success(
        self,
        db: Session,
        user_id: int | None,
        channel: str,
        provider: str | None = None,
        destination: str | None = None,
    ) -> dict[str, Any]:
        """Успех доставки: сбросить счётчик и снять подавление."""
        if not self._enabled():
            return {"enabled": False}
        row = safety_repo.record_success(
            db, user_id, channel, provider, hash_destination(destination)
        )
        return {"enabled": True, "reset": row is not None}

    def clear_suppression(
        self, db: Session, suppression_id: int, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """Вручную снять подавление (владелец/доступ проверяет API)."""
        row = safety_repo.get_suppression_by_id(db, suppression_id)
        if row is None:
            raise NotificationSuppressionError("Подавление не найдено")
        if (
            current_user_id is not None
            and row.user_id is not None
            and row.user_id != current_user_id
        ):
            raise NotificationSuppressionError("Нет доступа к подавлению")
        safety_repo.clear_suppression(db, row, current_user_id)
        self._write_audit(
            db,
            audit_actions.ACTION_NOTIFICATION_SUPPRESSION_CLEARED,
            row,
            {"suppression_id": row.id},
        )
        return self._view(row)

    def list_suppressions(
        self,
        db: Session,
        user_id: int | None = None,
        project_id: int | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Список подавлений (view без сырых адресов)."""
        rows = safety_repo.list_suppressions(
            db, user_id=user_id, project_id=project_id, status=status
        )
        return [self._view(r) for r in rows]

    def build_suppression_dashboard(
        self, db: Session, project_id: int | None = None, user_id: int | None = None
    ) -> dict[str, Any]:
        """Сводка подавлений: активные/по каналу."""
        rows = safety_repo.list_suppressions(db, user_id=user_id, project_id=project_id)
        by_channel: dict[str, int] = {}
        active = 0
        for r in rows:
            if r.status == "active":
                active += 1
                by_channel[r.channel] = by_channel.get(r.channel, 0) + 1
        return {
            "project_id": project_id,
            "user_id": user_id,
            "enabled": self._enabled(),
            "total": len(rows),
            "active": active,
            "by_channel": by_channel,
            "suppressions": [self._view(r) for r in rows[:100]],
        }

    @staticmethod
    def _view(row: NotificationSuppression) -> dict[str, Any]:
        return {
            "id": row.id,
            "channel": row.channel,
            "provider": row.provider,
            "reason": row.reason,
            "status": row.status,
            "failure_count": row.failure_count,
            "suppressed_until": row.suppressed_until.isoformat() if row.suppressed_until else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    def _enabled(self) -> bool:
        return bool(self._resolve_settings().notification_suppression_enabled_effective)

    def _threshold(self) -> int:
        return int(self._resolve_settings().notification_suppression_failure_threshold_safe)

    def _ttl_seconds(self) -> int:
        return int(self._resolve_settings().notification_suppression_ttl_seconds)

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _audit_svc(self) -> AuditLogService:
        if self._audit is None:
            from app.services.audit_log_service import AuditLogService

            self._audit = AuditLogService()
        return self._audit

    def _write_audit(
        self, db: Session, action: str, row: NotificationSuppression, extra: dict[str, Any]
    ) -> None:
        self._audit_svc().record(
            db,
            action,
            account_id=row.account_id,
            project_id=row.project_id,
            user_id=row.user_id,
            entity_type="notification_suppression",
            metadata=extra,
        )


def get_notification_suppression_service() -> NotificationSuppressionService:
    """DI-фабрика сервиса подавления."""
    return NotificationSuppressionService()
