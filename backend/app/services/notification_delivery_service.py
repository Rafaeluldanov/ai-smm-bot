"""Сервис доставки уведомлений (sandbox) — v0.5.1.

Создаёт delivery-задачи, «отправляет» их через mock-провайдеров (без сети), ведёт журнал
доставки, поддерживает retry/backoff и дашборд. РЕАЛЬНАЯ внешняя доставка выключена по
умолчанию: live-провайдеры отказываются, пока не включены external-флаг и live канала.

БЕЗОПАСНОСТЬ:
- destination только маской; ошибки/метаданные санитизируются (без токенов/секретов/путей);
- доставка НЕ роняет основной workflow; по умолчанию dry-run и без реальной отправки.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.repositories import (
    notification_delivery_repository as delivery_repo,
)
from app.repositories import (
    notification_repository,
    project_repository,
    user_repository,
)
from app.repositories import (
    notification_safety_repository as safety_repo,
)
from app.services import audit_log_service as audit_actions
from app.services.notification_delivery import (
    NotificationDeliveryProviderRegistry,
    NotificationDeliveryRequest,
    mask_destination,
    sanitize_error,
)
from app.services.notification_service import sanitize_text

if TYPE_CHECKING:
    from app.config import Settings
    from app.models.app_notification import AppNotification
    from app.models.notification_delivery_log import NotificationDeliveryLog
    from app.services.audit_log_service import AuditLogService
    from app.services.notification_rate_limit_service import NotificationRateLimitService
    from app.services.notification_suppression_service import NotificationSuppressionService

logger = get_logger(__name__)

_CHANNELS = ("email", "telegram", "webhook", "digest")


class NotificationDeliveryError(Exception):
    """Ошибка доставки (нет доступа/сущности/канала) — API → 400/403/404."""


class NotificationDeliveryService:
    """Sandbox-доставка уведомлений: delivery-задачи, mock-отправка, логи, retry, дашборд."""

    def __init__(
        self,
        providers: NotificationDeliveryProviderRegistry | None = None,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._providers = providers
        self._audit = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # 1. Preview (без записи)                                             #
    # ------------------------------------------------------------------ #

    def preview_delivery(
        self,
        db: Session,
        notification_id: int,
        channel: str,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Предпросмотр доставки: провайдер, masked destination, subject/preview, причины отказа."""
        notification = self._owned_notification(db, notification_id, current_user_id)
        channel = self._valid_channel(channel)
        destination = self._resolve_destination(db, channel, notification)
        provider = self._registry().resolve(channel)
        disabled = self._disabled_reasons(channel)
        self._write_audit(
            db,
            audit_actions.ACTION_NOTIFICATION_DELIVERY_PREVIEWED,
            notification,
            {"channel": channel, "provider": provider.provider_name},
        )
        return {
            "notification_id": notification.id,
            "channel": channel,
            "provider": provider.provider_name,
            "destination_masked": mask_destination(channel, destination),
            "subject": sanitize_text(notification.title, 255),
            "message_preview": sanitize_text(notification.message, 200),
            "external_delivery_enabled": self._external_enabled(),
            "will_send_externally": False,
            "disabled_reasons": disabled,
            "dry_run_default": True,
        }

    # ------------------------------------------------------------------ #
    # 2. Создание delivery-задачи                                         #
    # ------------------------------------------------------------------ #

    def create_delivery_job(
        self,
        db: Session,
        notification_id: int,
        channel: str,
        current_user_id: int | None = None,
    ) -> NotificationDeliveryLog:
        """Создать запись доставки (pending/skipped/disabled). Внешней отправки нет."""
        notification = self._owned_notification(db, notification_id, current_user_id)
        channel = self._valid_channel(channel)
        provider = self._registry().resolve(channel)
        destination = self._resolve_destination(db, channel, notification)
        status, reason = self._initial_status(db, channel, notification, destination)
        # Для email/digest рендерим шаблон: subject берём из письма; в metadata — тип шаблона.
        subject = sanitize_text(notification.title, 255)
        request_metadata: dict[str, Any] = {"notification_type": notification.notification_type}
        if channel in ("email", "digest"):
            rendered = self._render_email(db, notification)
            if rendered is not None:
                subject = sanitize_text(rendered.get("subject") or subject, 255)
                request_metadata.update(
                    {
                        "template_type": rendered.get("template_type"),
                        "render_format": "both",
                        "has_unsubscribe_footer": bool(rendered.get("has_unsubscribe_footer")),
                    }
                )
        log = delivery_repo.create_delivery_log(
            db,
            account_id=notification.account_id,
            project_id=notification.project_id,
            notification_id=notification.id,
            recipient_user_id=notification.recipient_user_id,
            provider=provider.provider_name,
            channel=channel,
            status=status,
            destination_masked=mask_destination(channel, destination),
            subject=subject,
            message_preview=sanitize_text(notification.message, 200),
            error_message=reason,
            request_metadata=request_metadata,
        )
        self._write_audit(
            db,
            audit_actions.ACTION_NOTIFICATION_DELIVERY_JOB_CREATED,
            notification,
            {"delivery_log_id": log.id, "channel": channel, "status": status},
        )
        if status != "pending":
            self._write_audit(
                db,
                audit_actions.ACTION_NOTIFICATION_DELIVERY_BLOCKED,
                notification,
                {"delivery_log_id": log.id, "channel": channel, "reason": reason},
            )
        return log

    # ------------------------------------------------------------------ #
    # 3. Отправка одной delivery-задачи                                   #
    # ------------------------------------------------------------------ #

    def send_delivery(
        self, db: Session, delivery_log_id: int, dry_run: bool = True
    ) -> dict[str, Any]:
        """«Отправить» задачу: dry-run → skipped; mock → sent; live-skeleton → disabled/failed."""
        log = delivery_repo.get_delivery_log_by_id(db, delivery_log_id)
        if log is None:
            raise NotificationDeliveryError("Запись доставки не найдена")
        if log.status in ("sent", "canceled"):
            return {**self._log_view(log), "outcome": log.status}
        if not self._delivery_enabled():
            delivery_repo.mark_disabled(db, log, "delivery subsystem disabled")
            self._audit_log(db, audit_actions.ACTION_NOTIFICATION_DELIVERY_DISABLED, log)
            return {**self._log_view(log), "outcome": "disabled"}
        if dry_run:
            delivery_repo.mark_skipped(db, log, "dry-run (no external delivery)")
            self._audit_log(db, audit_actions.ACTION_NOTIFICATION_DELIVERY_SKIPPED, log)
            return {**self._log_view(log), "outcome": "skipped", "dry_run": True}

        provider = self._registry().resolve(log.channel)
        notification = (
            notification_repository.get_notification_by_id(db, log.notification_id)
            if log.notification_id
            else None
        )
        subject = log.subject or ""
        message = log.message_preview or ""
        request_metadata: dict[str, Any] = {}
        # Для email рендерим полное письмо (subject/text/html) в ЗАПРОС (не в лог: без токена).
        if log.channel in ("email", "digest") and notification is not None:
            rendered = self._render_email(db, notification)
            if rendered is not None:
                subject = rendered.get("subject") or subject
                message = rendered.get("text_body") or message
                if rendered.get("html_body"):
                    request_metadata["html_body"] = rendered["html_body"]
        request = NotificationDeliveryRequest(
            provider=provider.provider_name,
            channel=log.channel,
            recipient_user_id=log.recipient_user_id,
            destination=self._resolve_destination(db, log.channel, notification),
            subject=subject,
            message=message,
            metadata=request_metadata,
        )
        try:
            result = provider.send(request)
        except Exception as exc:  # noqa: BLE001 — доставка не роняет workflow
            logger.warning("delivery provider raised for log_id=%s", delivery_log_id)
            self._suppression().record_delivery_failure(
                db,
                log.recipient_user_id,
                log.channel,
                destination=request.destination,
                account_id=log.account_id,
                project_id=log.project_id,
            )
            return self._handle_failure(
                db, log, sanitize_error(str(exc)) or "provider error", {"delivered": False}
            )

        if result.ok and result.status == "sent":
            delivery_repo.mark_sent(db, log, result.provider_message_id, result.response_metadata)
            # Safety-учёт: попытка съедает лимит, успех снимает подавление.
            self._record_rate_attempt(db, log)
            self._suppression().record_delivery_success(
                db, log.recipient_user_id, log.channel, destination=request.destination
            )
            self._audit_log(db, audit_actions.ACTION_NOTIFICATION_DELIVERY_SENT, log)
            return {**self._log_view(log), "outcome": "sent"}
        if result.status == "disabled":
            delivery_repo.mark_disabled(db, log, sanitize_error(result.error_message))
            self._audit_log(db, audit_actions.ACTION_NOTIFICATION_DELIVERY_DISABLED, log)
            return {**self._log_view(log), "outcome": "disabled"}
        # Ошибка доставки — фиксируем в подавлении (порог → suppress).
        self._suppression().record_delivery_failure(
            db,
            log.recipient_user_id,
            log.channel,
            destination=request.destination,
            account_id=log.account_id,
            project_id=log.project_id,
        )
        return self._handle_failure(
            db, log, sanitize_error(result.error_message), result.response_metadata
        )

    # ------------------------------------------------------------------ #
    # 4. Создать задачи и отправить по каналам                            #
    # ------------------------------------------------------------------ #

    def send_notification(
        self,
        db: Session,
        notification_id: int,
        channels: list[str] | None = None,
        dry_run: bool = True,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Создать delivery-задачи по каналам и «отправить» (по умолчанию dry-run, без внешней)."""
        target_channels = [self._valid_channel(c) for c in (channels or ["email"])]
        results: list[dict[str, Any]] = []
        for channel in target_channels:
            log = self.create_delivery_job(db, notification_id, channel, current_user_id)
            results.append(self.send_delivery(db, log.id, dry_run=dry_run))
        return {
            "notification_id": notification_id,
            "dry_run": dry_run,
            "channels": target_channels,
            "external_delivery_enabled": self._external_enabled(),
            "results": results,
        }

    # ------------------------------------------------------------------ #
    # 5. Повторные попытки                                                #
    # ------------------------------------------------------------------ #

    def retry_due_deliveries(
        self, db: Session, dry_run: bool = True, limit: int = 100
    ) -> dict[str, Any]:
        """Повторить доставку pending/retry_scheduled (backoff, max attempts)."""
        if not self._retry_enabled():
            return {"dry_run": dry_run, "retried": 0, "enabled": False}
        due = delivery_repo.list_pending_delivery_logs(db, limit=limit)
        retried = 0
        for log in due:
            self.send_delivery(db, log.id, dry_run=dry_run)
            retried += 1
        return {"dry_run": dry_run, "retried": retried, "enabled": True}

    # ------------------------------------------------------------------ #
    # 6. Дашборд доставки                                                 #
    # ------------------------------------------------------------------ #

    def build_delivery_dashboard(
        self, db: Session, project_id: int | None = None, user_id: int | None = None
    ) -> dict[str, Any]:
        """Сводка доставки: по статусу/каналу/провайдеру + failed/pending/disabled."""
        summary = delivery_repo.get_delivery_dashboard_summary(db, project_id, user_id)
        by_status = summary["by_status"]
        return {
            "project_id": project_id,
            "user_id": user_id,
            "total": summary["total"],
            "pending": by_status.get("pending", 0),
            "sent": by_status.get("sent", 0),
            "failed": by_status.get("failed", 0),
            "skipped": by_status.get("skipped", 0),
            "disabled": by_status.get("disabled", 0),
            "retry_scheduled": by_status.get("retry_scheduled", 0),
            "by_status": by_status,
            "by_channel": summary["by_channel"],
            "by_provider": summary["by_provider"],
            "external_delivery_enabled": self._external_enabled(),
        }

    def list_user_delivery_logs(
        self,
        db: Session,
        user_id: int,
        status: str | None = None,
        channel: str | None = None,
        provider: str | None = None,
        project_id: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Логи доставки пользователя (view без секретов)."""
        rows = delivery_repo.list_delivery_logs_for_user(
            db,
            user_id,
            status=status,
            channel=channel,
            provider=provider,
            project_id=project_id,
            limit=limit,
        )
        return [self._log_view(r) for r in rows]

    # ------------------------------------------------------------------ #
    # 7. mask_destination (публичный хелпер)                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def mask_destination(channel: str, destination: str | None) -> str:
        """Замаскировать адрес доставки (email/telegram/webhook)."""
        return mask_destination(channel, destination)

    # ------------------------------------------------------------------ #
    # Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    def _handle_failure(
        self,
        db: Session,
        log: NotificationDeliveryLog,
        error_message: str | None,
        response_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        max_attempts = self._max_attempts()
        if self._retry_enabled() and (log.attempts + 1) < max_attempts:
            delivery_repo.schedule_retry(db, log, self._backoff_seconds(), error_message)
            self._audit_log(db, audit_actions.ACTION_NOTIFICATION_DELIVERY_RETRY_SCHEDULED, log)
            return {**self._log_view(log), "outcome": "retry_scheduled"}
        delivery_repo.mark_failed(db, log, error_message, response_metadata)
        self._audit_log(db, audit_actions.ACTION_NOTIFICATION_DELIVERY_FAILED, log)
        return {**self._log_view(log), "outcome": "failed"}

    def _initial_status(
        self,
        db: Session,
        channel: str,
        notification: AppNotification,
        destination: str | None = None,
    ) -> tuple[str, str | None]:
        """Определить статус задачи с учётом safety-гейтов (opt-out/suppression/rate-limit)."""
        if not self._delivery_enabled():
            return "disabled", "external_delivery_disabled"
        uid = notification.recipient_user_id
        # 1. Нет адреса доставки (для digest адрес — email получателя, проверяем тоже).
        if not destination:
            return "disabled", "missing_destination"
        # 2. Предпочтение канала выключено.
        pref = (
            notification_repository.get_preference(db, uid, channel, None, notification.account_id)
            if uid
            else None
        )
        if pref is not None and not pref.enabled:
            return "skipped", "preference_disabled"
        # 3-5. Safety-гейты (только если safety включён и есть получатель).
        if self._safety_enabled() and uid is not None:
            if (
                safety_repo.is_opted_out(
                    db,
                    uid,
                    channel=channel,
                    notification_type=notification.notification_type,
                    project_id=notification.project_id,
                    account_id=notification.account_id,
                )
                is not None
            ):
                return "disabled", "user_unsubscribed"
            if self._suppression().is_suppressed(db, uid, channel, destination=destination):
                return "disabled", "too_many_failures"
            rl = self._rate_limit().check_delivery_allowed(
                db,
                uid,
                channel,
                project_id=notification.project_id,
                notification_type=notification.notification_type,
                account_id=notification.account_id,
            )
            if not rl.get("allowed", True):
                return "skipped", "rate_limited"
        return "pending", None

    def _disabled_reasons(self, channel: str) -> list[str]:
        reasons: list[str] = []
        if not self._external_enabled():
            reasons.append(
                "Внешняя доставка выключена (NOTIFICATION_EXTERNAL_DELIVERY_ENABLED=false)"
            )
        channel_effective = {
            "email": self._settings_val("notification_email_enabled_effective"),
            "telegram": self._settings_val("notification_telegram_enabled_effective"),
            "webhook": self._settings_val("notification_webhook_enabled_effective"),
            "digest": self._settings_val("notification_email_enabled_effective"),
        }.get(channel, False)
        if not channel_effective:
            reasons.append(f"Канал {channel}: live отключён (используется mock/sandbox)")
        return reasons

    def _resolve_destination(
        self, db: Session, channel: str, notification: AppNotification | None
    ) -> str | None:
        if notification is None:
            return None
        uid = notification.recipient_user_id
        if channel in ("email", "digest"):
            user = user_repository.get_user_by_id(db, uid) if uid else None
            return user.email if user is not None else None
        if channel == "telegram":
            configured = self._resolve_settings().notification_telegram_default_chat_id
            return configured or (f"chat:{uid}" if uid else None)
        if channel == "webhook":
            return "https://sandbox.local/notify"
        return None

    def _owned_notification(
        self, db: Session, notification_id: int, current_user_id: int | None
    ) -> AppNotification:
        notification = notification_repository.get_notification_by_id(db, notification_id)
        if notification is None:
            raise NotificationDeliveryError("Уведомление не найдено")
        if current_user_id is not None and notification.recipient_user_id != current_user_id:
            raise NotificationDeliveryError("Нет доступа к уведомлению")
        return notification

    @staticmethod
    def _valid_channel(channel: str) -> str:
        if channel not in _CHANNELS:
            raise NotificationDeliveryError(f"Неизвестный канал: {channel}")
        return channel

    def _account_id(self, db: Session, project_id: int | None) -> int | None:
        if project_id is None:
            return None
        project = project_repository.get_project_by_id(db, project_id)
        return project.account_id if project is not None else None

    def _log_view(self, log: NotificationDeliveryLog) -> dict[str, Any]:
        return {
            "id": log.id,
            "project_id": log.project_id,
            "notification_id": log.notification_id,
            "recipient_user_id": log.recipient_user_id,
            "provider": log.provider,
            "channel": log.channel,
            "status": log.status,
            "destination_masked": log.destination_masked,
            "subject": log.subject,
            "message_preview": log.message_preview,
            "attempts": log.attempts,
            "provider_message_id": log.provider_message_id,
            "error_message": log.error_message,
            "next_retry_at": log.next_retry_at.isoformat() if log.next_retry_at else None,
            "sent_at": log.sent_at.isoformat() if log.sent_at else None,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }

    # --- audit ---

    def _write_audit(
        self, db: Session, action: str, notification: AppNotification, extra: dict[str, Any]
    ) -> None:
        self._audit_svc().record(
            db,
            action,
            account_id=notification.account_id,
            project_id=notification.project_id,
            user_id=notification.recipient_user_id,
            entity_type="notification_delivery",
            metadata={"notification_id": notification.id, **extra},
        )

    def _audit_log(self, db: Session, action: str, log: NotificationDeliveryLog) -> None:
        self._audit_svc().record(
            db,
            action,
            account_id=log.account_id,
            project_id=log.project_id,
            user_id=log.recipient_user_id,
            entity_type="notification_delivery",
            metadata={
                "delivery_log_id": log.id,
                "channel": log.channel,
                "provider": log.provider,
                "status": log.status,
            },
        )

    # --- settings/deps ---

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _settings_val(self, name: str) -> bool:
        return bool(getattr(self._resolve_settings(), name, False))

    def _registry(self) -> NotificationDeliveryProviderRegistry:
        if self._providers is None:
            self._providers = NotificationDeliveryProviderRegistry(self._resolve_settings())
        return self._providers

    def _safety_enabled(self) -> bool:
        return bool(self._resolve_settings().notification_safety_enabled_effective)

    def _suppression(self) -> NotificationSuppressionService:
        if getattr(self, "_suppression_svc", None) is None:
            from app.services.notification_suppression_service import (
                NotificationSuppressionService,
            )

            self._suppression_svc = NotificationSuppressionService(settings=self._settings)
        return self._suppression_svc

    def _rate_limit(self) -> NotificationRateLimitService:
        if getattr(self, "_rate_limit_svc", None) is None:
            from app.services.notification_rate_limit_service import NotificationRateLimitService

            self._rate_limit_svc = NotificationRateLimitService(settings=self._settings)
        return self._rate_limit_svc

    def _render_email(self, db: Session, notification: Any) -> dict[str, Any] | None:
        """Отрендерить email для уведомления (безопасно; не роняет доставку)."""
        if not bool(getattr(self._resolve_settings(), "email_templates_enabled_effective", True)):
            return None
        try:
            from app.services.email_template_service import EmailTemplateService

            if getattr(self, "_email_tpl_svc", None) is None:
                self._email_tpl_svc = EmailTemplateService(settings=self._settings)
            # reveal=False: в лог/запрос попадает ТОЛЬКО masked unsubscribe URL (без сырого токена).
            return self._email_tpl_svc.render_notification_email(
                db, notification.id, reveal_unsubscribe=False
            )
        except Exception:  # noqa: BLE001 — рендер не критичен для доставки
            logger.warning("email render failed for notification_id=%s", notification.id)
            return None

    def _record_rate_attempt(self, db: Session, log: NotificationDeliveryLog) -> None:
        self._rate_limit().record_delivery_attempt(
            db,
            log.recipient_user_id,
            log.channel,
            provider=log.provider,
            project_id=log.project_id,
            account_id=log.account_id,
        )

    def _delivery_enabled(self) -> bool:
        return bool(self._resolve_settings().notification_delivery_enabled_effective)

    def _external_enabled(self) -> bool:
        return bool(self._resolve_settings().notification_external_delivery_enabled_effective)

    def _retry_enabled(self) -> bool:
        return bool(self._resolve_settings().notification_delivery_retry_enabled)

    def _max_attempts(self) -> int:
        return int(self._resolve_settings().notification_delivery_max_attempts_safe)

    def _backoff_seconds(self) -> int:
        return int(self._resolve_settings().notification_delivery_retry_backoff_seconds_safe)

    def _audit_svc(self) -> AuditLogService:
        if self._audit is None:
            from app.services.audit_log_service import AuditLogService

            self._audit = AuditLogService()
        return self._audit


def get_notification_delivery_service() -> NotificationDeliveryService:
    """DI-фабрика сервиса доставки уведомлений."""
    return NotificationDeliveryService()
