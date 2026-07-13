"""Сервис обработки входящих Telegram-обновлений (webhook/polling sandbox) — v0.5.5.

Принимает Telegram Update (из webhook-эндпоинта или симуляции), проверяет secret-заголовок,
парсит апдейт, логирует его и — если это ``/start <token>`` — автоматически верифицирует привязку
через ``NotificationTelegramBindingService``. Ответных сообщений наружу НЕ отправляет; реальных
Telegram API-вызовов нет.

БЕЗОПАСНОСТЬ:
- сырой chat_id / verification token / bot token / webhook secret не пишутся в лог;
- в лог идут только hash + маска + санитизированная копия апдейта;
- сбой верификации не роняет обработку (апдейт помечается failed).
"""

from __future__ import annotations

import hmac
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.core.redaction import redact_sensitive_text
from app.repositories import notification_telegram_update_repository as update_repo
from app.services import audit_log_service as audit_actions
from app.services.notification_telegram_binding_service import (
    NotificationTelegramBindingService,
    TelegramBindingError,
)
from app.services.telegram_update_parser_service import (
    ParsedTelegramUpdate,
    TelegramUpdateParserService,
    hash_telegram_id,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.notification_telegram_update_log import NotificationTelegramUpdateLog
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


class TelegramIncomingService:
    """Обработка входящих Telegram-апдейтов: secret-check, парсинг, лог, авто-верификация /start."""

    def __init__(
        self,
        binding_service: NotificationTelegramBindingService | None = None,
        parser_service: TelegramUpdateParserService | None = None,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._binding = binding_service
        self._parser = parser_service
        self._audit = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Основная обработка                                                  #
    # ------------------------------------------------------------------ #

    def handle_webhook_update(
        self,
        db: Session,
        update_payload: dict[str, Any],
        secret_header: str | None = None,
        request_ip: str | None = None,  # noqa: ARG002 — резерв для будущего allowlist/лога
    ) -> dict[str, Any]:
        """Обработать входящий Telegram-апдейт (без сети, без исходящих сообщений)."""
        settings = self._resolve_settings()
        if not settings.notification_telegram_webhook_enabled_effective:
            return {"ok": False, "status": "disabled", "reason": "webhook endpoint disabled"}

        parsed = self._parser_svc().parse_update(update_payload)

        # 1. Secret-заголовок (если требуется).
        if not self.verify_secret_header(secret_header):
            log = self._create_log(db, parsed, "invalid_secret")
            self._audit_update(db, audit_actions.ACTION_TELEGRAM_UPDATE_INVALID_SECRET, log)
            return self.public_result({"ok": False, "status": "invalid_secret", "log_id": log.id})

        # 2. Дедупликация по update_id.
        if parsed.update_id is not None:
            prior = update_repo.get_by_update_id(db, parsed.update_id)
            if prior is not None:
                log = self._create_log(db, parsed, "duplicate")
                self._audit_update(db, audit_actions.ACTION_TELEGRAM_UPDATE_DUPLICATE, log)
                return self.public_result({"ok": True, "status": "duplicate", "log_id": log.id})

        # 3. Создать запись received + аудит.
        log = self._create_log(db, parsed, "received")
        self._audit_update(db, audit_actions.ACTION_TELEGRAM_UPDATE_RECEIVED, log)

        # 4. /start <token> → авто-верификация привязки.
        if parsed.is_start_command and parsed.start_token and parsed.chat_id:
            return self._process_start(db, log, update_payload)

        # 5. Прочие команды/сообщения — processed/ignored (ответа наружу нет).
        if parsed.command in ("help", "status"):
            update_repo.mark_processed(db, log, _now(), result_metadata={"command": parsed.command})
            return self.public_result(
                {"ok": True, "status": "processed", "command": parsed.command, "log_id": log.id}
            )
        reason = parsed.unknown_reason or "no actionable command"
        update_repo.mark_ignored(db, log, _now(), reason=reason)
        self._audit_update(db, audit_actions.ACTION_TELEGRAM_UPDATE_IGNORED, log)
        return self.public_result({"ok": True, "status": "ignored", "log_id": log.id})

    def _process_start(
        self, db: Session, log: NotificationTelegramUpdateLog, update_payload: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            result = self._binding_svc().verify_binding_from_update(db, update_payload)
        except TelegramBindingError as exc:
            update_repo.mark_failed(db, log, _now(), error=_sanitize(str(exc)))
            self._audit_update(db, audit_actions.ACTION_TELEGRAM_UPDATE_FAILED, log)
            return self.public_result(
                {"ok": False, "status": "failed", "reason": _sanitize(str(exc)), "log_id": log.id}
            )
        update_repo.mark_verified_binding(
            db,
            log,
            _now(),
            binding_id=result.get("binding_id"),
            user_id=result.get("user_id"),
            account_id=result.get("account_id"),
            project_id=result.get("project_id"),
            result_metadata={"chat_id_masked": result.get("chat_id_masked")},
        )
        self._audit_update(db, audit_actions.ACTION_TELEGRAM_UPDATE_VERIFIED_BINDING, log)
        return self.public_result(
            {
                "ok": True,
                "status": "verified_binding",
                "binding_id": result.get("binding_id"),
                "chat_id_masked": result.get("chat_id_masked"),
                "log_id": log.id,
            }
        )

    # ------------------------------------------------------------------ #
    # Симуляция (UI/CLI/тесты)                                            #
    # ------------------------------------------------------------------ #

    def simulate_update(
        self,
        db: Session,
        token: str,
        chat_id: str,
        telegram_user_id: str | None = None,
        username: str | None = None,
        update_id: int | None = None,
    ) -> dict[str, Any]:
        """Собрать фейковый ``/start``-апдейт и прогнать через handle_webhook_update (sandbox)."""
        payload: dict[str, Any] = {
            "update_id": update_id,
            "message": {
                "text": f"/start {token}".strip(),
                "chat": {"id": chat_id, "type": "private"},
                "from": {"id": telegram_user_id or chat_id, "username": username, "is_bot": False},
            },
        }
        # Симуляция всегда с валидным secret (локальный sandbox).
        secret = self._resolve_settings().notification_telegram_webhook_secret_token or None
        return self.handle_webhook_update(db, payload, secret_header=secret)

    # ------------------------------------------------------------------ #
    # Дашборд / secret                                                   #
    # ------------------------------------------------------------------ #

    def build_webhook_dashboard(
        self, db: Session, user_id: int | None = None, project_id: int | None = None
    ) -> dict[str, Any]:
        """Сводка webhook-канала: недавние апдейты, счётчики статусов, URL, live-флаги, secret."""
        settings = self._resolve_settings()
        if project_id is not None:
            logs = update_repo.list_for_project(db, project_id)
        elif user_id is not None:
            logs = update_repo.list_for_user(db, user_id)
        else:
            logs = update_repo.list_recent(db)
        return {
            "webhook_url": settings.notification_telegram_webhook_public_url_effective,
            "webhook_path": settings.notification_telegram_webhook_path_effective,
            "secret_required": settings.notification_telegram_webhook_secret_required_effective,
            "secret_configured": bool(
                (settings.notification_telegram_webhook_secret_token or "").strip()
            ),
            "recent_updates": [update_repo.public_update_view(x) for x in logs[:20]],
            "counts": update_repo.dashboard_summary(logs),
            "flags": {
                "webhook_enabled": settings.notification_telegram_webhook_enabled_effective,
                "webhook_live_enabled": (
                    settings.notification_telegram_webhook_live_enabled_effective
                ),
                "polling_enabled": settings.notification_telegram_polling_enabled_effective,
                "polling_live_enabled": (
                    settings.notification_telegram_polling_live_enabled_effective
                ),
                "management_live_enabled": (
                    settings.notification_telegram_webhook_management_live_enabled_effective
                ),
                "external_delivery_enabled": (
                    settings.notification_external_delivery_enabled_effective
                ),
                "configured": settings.notification_telegram_configured,
            },
        }

    def verify_secret_header(self, header_value: str | None) -> bool:
        """Проверить X-Telegram-Bot-Api-Secret-Token. По умолчанию secret не требуется (sandbox)."""
        settings = self._resolve_settings()
        if not settings.notification_telegram_webhook_secret_required_effective:
            return True
        expected = (settings.notification_telegram_webhook_secret_token or "").strip()
        if not expected:
            # Требуется secret, но он не сконфигурирован → в local можно пропустить по флагу.
            return bool(settings.notification_telegram_webhook_allow_local_without_secret)
        provided = (header_value or "").strip()
        if not provided:
            return False
        # Сравнение в постоянном времени (защита от timing-атак).
        return hmac.compare_digest(provided, expected)

    def public_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """Очистить результат для отдачи наружу (без сырого токена/chat_id/секретов)."""
        allowed = (
            "ok",
            "status",
            "reason",
            "command",
            "binding_id",
            "chat_id_masked",
            "log_id",
        )
        return {k: result[k] for k in allowed if k in result}

    # ------------------------------------------------------------------ #
    # Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    def _create_log(
        self, db: Session, parsed: ParsedTelegramUpdate, status: str
    ) -> NotificationTelegramUpdateLog:
        settings = self._resolve_settings()
        preview_limit = settings.notification_telegram_incoming_max_text_preview_safe
        from app.services.telegram_update_parser_service import mask_start_token

        text_preview = None
        if parsed.text is not None:
            text_preview = _sanitize(mask_start_token(parsed.text))[:preview_limit]
        return update_repo.create_update_log(
            db,
            update_id=parsed.update_id,
            update_type=parsed.update_type,
            status=status,
            command=parsed.command,
            chat_id_hash=hash_telegram_id(parsed.chat_id),
            telegram_user_id_hash=hash_telegram_id(parsed.telegram_user_id),
            username=(parsed.username or None),
            text_preview=text_preview,
            raw_update_sanitized=parsed.raw_sanitized,
            received_at=_now(),
        )

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _binding_svc(self) -> NotificationTelegramBindingService:
        if self._binding is None:
            self._binding = NotificationTelegramBindingService(settings=self._settings)
        return self._binding

    def _parser_svc(self) -> TelegramUpdateParserService:
        if self._parser is None:
            self._parser = TelegramUpdateParserService()
        return self._parser

    def _audit_svc(self) -> AuditLogService:
        if self._audit is None:
            from app.services.audit_log_service import AuditLogService

            self._audit = AuditLogService()
        return self._audit

    def _audit_update(self, db: Session, action: str, log: NotificationTelegramUpdateLog) -> None:
        self._audit_svc().record(
            db,
            action,
            account_id=log.account_id,
            project_id=log.project_id,
            user_id=log.user_id,
            entity_type="telegram_update",
            entity_id=log.id,
            metadata={
                "update_type": log.update_type,
                "command": log.command,
                "status": log.status,
            },
        )


def _sanitize(text: str | None) -> str:
    """Санитизировать текст (убрать секреты/токены-провайдеров)."""
    return redact_sensitive_text(text or "")[:512]


def get_telegram_incoming_service() -> TelegramIncomingService:
    """DI-фабрика сервиса входящих Telegram-апдейтов."""
    return TelegramIncomingService()
