"""Сервис подписок на webhook — v0.5.2.

Клиент задаёт webhook URL и (опционально) signing secret. URL и секрет считаются
чувствительными: хранятся зашифрованно (``crm_secret_service``) + masked/hash; наружу отдаётся
ТОЛЬКО masked/hash. Payload подписывается HMAC-SHA256. Реальный вызов ВЫКЛЮЧЕН по умолчанию —
доступен только mock preview (подписанный payload без отправки).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.repositories import (
    notification_repository,
    project_repository,
)
from app.repositories import (
    notification_safety_repository as safety_repo,
)
from app.services import audit_log_service as audit_actions
from app.services import crm_secret_service
from app.services.notification_service import sanitize_text

if TYPE_CHECKING:
    from app.config import Settings
    from app.models.webhook_subscription import WebhookSubscription
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

_URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)


def mask_url(url: str | None) -> str | None:
    """Замаскировать webhook URL: схема + домен, путь скрыт."""
    value = (url or "").strip()
    if not value:
        return None
    m = re.match(r"^(https?)://([^/]+)", value)
    if not m:
        return "***"
    return f"{m.group(1)}://{m.group(2)}/***"


def hash_url(url: str | None) -> str | None:
    """SHA-256 hash URL (для дедупликации/поиска без раскрытия)."""
    if not url:
        return None
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:64]


class WebhookSubscriptionError(Exception):
    """Ошибка webhook-подписки (нет доступа/сущности/невалидный URL) — API → 400/404."""


class WebhookSubscriptionService:
    """Подписки webhook: create/update/revoke/list + HMAC-подпись + mock preview (без отправки)."""

    def __init__(
        self, audit_service: AuditLogService | None = None, settings: Settings | None = None
    ) -> None:
        self._audit = audit_service
        self._settings = settings

    # --- CRUD --- #

    def create_subscription(
        self,
        db: Session,
        account_id: int,
        title: str,
        url: str,
        event_types: list[str] | None = None,
        project_id: int | None = None,
        user_id: int | None = None,
        signing_secret: str | None = None,
    ) -> dict[str, Any]:
        """Создать подписку: URL/secret шифруются и маскируются; секрет генерируется если пуст."""
        url = (url or "").strip()
        if not _URL_RE.match(url):
            raise WebhookSubscriptionError("Некорректный webhook URL (нужен http(s)://)")
        secret = (signing_secret or "").strip() or secrets.token_urlsafe(32)
        sub = safety_repo.create_webhook_subscription(
            db,
            account_id=account_id,
            project_id=project_id,
            user_id=user_id,
            title=sanitize_text(title or "webhook", 255),
            status="draft",
            url_masked=mask_url(url),
            url_hash=hash_url(url),
            url_encrypted=crm_secret_service.encrypt_secret(url),
            signing_secret_encrypted=crm_secret_service.encrypt_secret(secret),
            signing_secret_masked=crm_secret_service.mask_secret(secret),
            signature_algorithm="hmac_sha256",
            event_types=list(event_types or ["notification"]),
        )
        self._write_audit(
            db,
            audit_actions.ACTION_WEBHOOK_SUBSCRIPTION_CREATED,
            sub,
            {"subscription_id": sub.id},
        )
        return self._view(sub)

    def update_subscription(
        self,
        db: Session,
        subscription_id: int,
        current_user_id: int | None = None,
        title: str | None = None,
        status: str | None = None,
        event_types: list[str] | None = None,
        url: str | None = None,
        signing_secret: str | None = None,
    ) -> dict[str, Any]:
        """Обновить подписку (title/status/event_types/URL/secret). Секреты не возвращаются."""
        sub = self._get(db, subscription_id)
        fields: dict[str, Any] = {}
        if title is not None:
            fields["title"] = sanitize_text(title, 255)
        if status is not None and status in ("draft", "active", "disabled"):
            fields["status"] = status
        if event_types is not None:
            fields["event_types"] = list(event_types)
        if url is not None:
            url = url.strip()
            if not _URL_RE.match(url):
                raise WebhookSubscriptionError("Некорректный webhook URL")
            fields["url_masked"] = mask_url(url)
            fields["url_hash"] = hash_url(url)
            fields["url_encrypted"] = crm_secret_service.encrypt_secret(url)
        if signing_secret is not None and signing_secret.strip():
            fields["signing_secret_encrypted"] = crm_secret_service.encrypt_secret(
                signing_secret.strip()
            )
            fields["signing_secret_masked"] = crm_secret_service.mask_secret(signing_secret.strip())
        safety_repo.update_webhook_subscription(db, sub, **fields)
        self._write_audit(
            db,
            audit_actions.ACTION_WEBHOOK_SUBSCRIPTION_UPDATED,
            sub,
            {"subscription_id": sub.id},
        )
        return self._view(sub)

    def revoke_subscription(
        self, db: Session, subscription_id: int, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """Отозвать подписку."""
        sub = self._get(db, subscription_id)
        safety_repo.revoke_webhook_subscription(db, sub, current_user_id)
        self._write_audit(
            db,
            audit_actions.ACTION_WEBHOOK_SUBSCRIPTION_REVOKED,
            sub,
            {"subscription_id": sub.id},
        )
        return self._view(sub)

    def list_subscriptions(
        self,
        db: Session,
        account_id: int | None = None,
        project_id: int | None = None,
        user_id: int | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Список подписок (view без сырых URL/secret)."""
        rows = safety_repo.list_webhook_subscriptions(
            db, account_id=account_id, project_id=project_id, user_id=user_id, status=status
        )
        return [self._view(r) for r in rows]

    def get_subscription(self, db: Session, subscription_id: int) -> dict[str, Any]:
        """Одна подписка (view)."""
        return self._view(self._get(db, subscription_id))

    # --- Подпись / payload --- #

    def sign_payload(self, payload_bytes: bytes, secret: str, timestamp: int) -> str:
        """HMAC-SHA256 подпись ``{timestamp}.{payload}`` (детерминированная)."""
        message = f"{timestamp}.".encode() + payload_bytes
        mac = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
        return f"sha256={mac}"

    def build_webhook_payload(self, notification: Any) -> dict[str, Any]:
        """Собрать безопасный payload webhook по уведомлению (без секретов)."""
        return {
            "event": "notification",
            "notification_id": getattr(notification, "id", None),
            "notification_type": getattr(notification, "notification_type", None),
            "project_id": getattr(notification, "project_id", None),
            "priority": getattr(notification, "priority", None),
            "title": sanitize_text(getattr(notification, "title", "") or "", 200),
            "message_preview": sanitize_text(getattr(notification, "message", "") or "", 200),
        }

    def preview_webhook_delivery(
        self, db: Session, subscription_id: int, notification_id: int | None = None
    ) -> dict[str, Any]:
        """Показать подписанный payload, который БЫЛ БЫ отправлен (без реального вызова)."""
        sub = self._get(db, subscription_id)
        notification = (
            notification_repository.get_notification_by_id(db, notification_id)
            if notification_id
            else None
        )
        payload = (
            self.build_webhook_payload(notification)
            if notification is not None
            else {"event": "notification.test", "subscription_id": sub.id}
        )
        payload_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
        timestamp = int(time.time())
        signature = "not_available"
        if sub.signing_secret_encrypted:
            secret = crm_secret_service.decrypt_secret(sub.signing_secret_encrypted)
            signature = self.sign_payload(payload_bytes, secret, timestamp)
        settings = self._resolve_settings()
        self._write_audit(
            db,
            audit_actions.ACTION_WEBHOOK_SUBSCRIPTION_PREVIEWED,
            sub,
            {"subscription_id": sub.id, "notification_id": notification_id},
        )
        return {
            "subscription_id": sub.id,
            "url_masked": sub.url_masked,
            "signature_algorithm": sub.signature_algorithm,
            "signature_header": settings.notification_webhook_signature_header,
            "timestamp_header": settings.notification_webhook_timestamp_header,
            "timestamp": timestamp,
            "signature": signature,
            "payload": payload,
            "would_send": False,
            "live_enabled": bool(
                settings.notification_webhook_subscriptions_live_enabled_effective
            ),
        }

    def create_webhook_delivery_job(
        self, db: Session, subscription_id: int, notification_id: int
    ) -> dict[str, Any]:
        """Создать delivery-задачу webhook по подписке (в MVP disabled — live выключен)."""
        from app.repositories import notification_delivery_repository as delivery_repo

        sub = self._get(db, subscription_id)
        notification = notification_repository.get_notification_by_id(db, notification_id)
        live = self._resolve_settings().notification_webhook_subscriptions_live_enabled_effective
        status = "pending" if live else "disabled"
        reason = None if live else "webhook live delivery disabled"
        log = delivery_repo.create_delivery_log(
            db,
            account_id=sub.account_id,
            project_id=sub.project_id,
            notification_id=notification_id,
            recipient_user_id=getattr(notification, "recipient_user_id", None),
            provider="webhook",
            channel="webhook",
            status=status,
            destination_masked=sub.url_masked,
            subject=sanitize_text(getattr(notification, "title", "") or "webhook", 255),
            error_message=reason,
            request_metadata={"subscription_id": sub.id},
        )
        return {"delivery_log_id": log.id, "status": status, "live_enabled": live}

    # --- Внутреннее --- #

    def _get(self, db: Session, subscription_id: int) -> WebhookSubscription:
        sub = safety_repo.get_webhook_subscription_by_id(db, subscription_id)
        if sub is None:
            raise WebhookSubscriptionError("Подписка webhook не найдена")
        return sub

    @staticmethod
    def _view(sub: WebhookSubscription) -> dict[str, Any]:
        # ВНИМАНИЕ: НИКОГДА не отдаём url_encrypted/signing_secret_encrypted/сырые значения.
        return {
            "id": sub.id,
            "account_id": sub.account_id,
            "project_id": sub.project_id,
            "title": sub.title,
            "status": sub.status,
            "url_masked": sub.url_masked,
            "url_hash": sub.url_hash,
            "signing_secret_present": bool(sub.signing_secret_encrypted),
            "signing_secret_masked": sub.signing_secret_masked,
            "signature_algorithm": sub.signature_algorithm,
            "event_types": list(sub.event_types or []),
            "failure_count": sub.failure_count,
            "last_error": sub.last_error,
            "created_at": sub.created_at.isoformat() if sub.created_at else None,
        }

    def _account_id(self, db: Session, project_id: int | None) -> int | None:
        if project_id is None:
            return None
        project = project_repository.get_project_by_id(db, project_id)
        return project.account_id if project is not None else None

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
        self, db: Session, action: str, sub: WebhookSubscription, extra: dict[str, Any]
    ) -> None:
        self._audit_svc().record(
            db,
            action,
            account_id=sub.account_id,
            project_id=sub.project_id,
            user_id=sub.user_id,
            entity_type="webhook_subscription",
            metadata=extra,
        )


def get_webhook_subscription_service() -> WebhookSubscriptionService:
    """DI-фабрика сервиса webhook-подписок."""
    return WebhookSubscriptionService()
