"""Сервис привязки Telegram-канала уведомлений — v0.5.4.

Поток: пользователь запрашивает binding → система выдаёт verification token (показывается ОДИН
раз) → пользователь отправляет боту ``/start <token>`` → Botfleet сохраняет chat_id (encrypted).
Пока live-доставка выключена (по умолчанию) — всё sandbox; реальных сообщений наружу нет.

БЕЗОПАСНОСТЬ:
- chat_id / telegram_user_id хранятся ТОЛЬКО encrypted (crm_secret_service) + masked + sha256-hash;
- сырой chat_id/токен наружу (API/UI/логи) НЕ отдаётся; токен — только в момент создания;
- verification token хранится как sha256-hash + prefix; сравнение по hash;
- никакого bot token в этом слое.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.repositories import notification_telegram_repository as telegram_repo
from app.services import audit_log_service as audit_actions
from app.services import crm_secret_service

if TYPE_CHECKING:
    from app.config import Settings
    from app.models.notification_telegram_binding import NotificationTelegramBinding
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)


class TelegramBindingError(Exception):
    """Ошибка привязки Telegram (нет доступа/сущности/невалидный токен) — API → 400/403/404."""


def _now() -> datetime:
    return datetime.now(UTC)


def hash_chat_id(chat_id: str) -> str:
    """sha256-hash chat_id (для индексируемого поиска без раскрытия значения)."""
    return hashlib.sha256(str(chat_id).strip().encode("utf-8")).hexdigest()[:64]


def mask_chat_id(chat_id: str) -> str:
    """Маска chat_id для UI/логов (без раскрытия полного значения)."""
    value = str(chat_id or "").strip()
    if not value:
        return "—"
    if len(value) <= 4:
        return "***"
    return f"{value[:2]}***{value[-2:]}"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()[:64]


class NotificationTelegramBindingService:
    """Создание/верификация/отзыв привязок Telegram-чата; безопасное хранение chat_id."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Создание токена привязки                                          #
    # ------------------------------------------------------------------ #

    def create_binding_token(
        self,
        db: Session,
        user_id: int,
        account_id: int | None = None,
        project_id: int | None = None,
        title: str | None = None,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Создать/обновить pending-привязку и вернуть verification token (показ ОДИН раз)."""
        if not self._binding_enabled():
            raise TelegramBindingError("Привязка Telegram выключена (binding disabled)")
        settings = self._resolve_settings()
        token_bytes = max(16, int(settings.notification_telegram_binding_token_bytes or 24))
        token = secrets.token_urlsafe(token_bytes)
        token_hash = _hash_token(token)
        token_prefix = token[:8]

        # Переиспользуем существующую не-verified привязку пользователя того же scope, иначе новую.
        existing = self._find_reusable_binding(db, user_id, account_id, project_id)
        if existing is not None:
            binding = telegram_repo.mark_pending(db, existing, token_hash, token_prefix)
            if title is not None:
                binding = telegram_repo.update_binding(db, binding, title=title)
        else:
            binding = telegram_repo.create_binding(
                db,
                user_id=user_id,
                account_id=account_id,
                project_id=project_id,
                title=title,
                status="pending_verification",
                verification_token_hash=token_hash,
                verification_token_prefix=token_prefix,
            )
        self._write_audit(
            db,
            audit_actions.ACTION_TELEGRAM_BINDING_CREATED,
            account_id=account_id,
            project_id=project_id,
            user_id=current_user_id or user_id,
            metadata={"binding_id": binding.id, "token_prefix": token_prefix},
        )
        return {
            "binding_id": binding.id,
            "status": binding.status,
            # Сырой токен отдаётся ТОЛЬКО здесь (в момент создания) и НЕ логируется целиком.
            "verification_token": token,
            "verification_token_prefix": token_prefix,
            "bot_command": f"/start {token}",
            "expires_in_seconds": settings.notification_telegram_binding_token_ttl_seconds,
            "instructions": [
                "Откройте вашего Telegram-бота Botfleet.",
                f"Отправьте боту команду: /start {token}",
                "Вернитесь сюда и нажмите «Проверить» (или дождитесь подтверждения).",
            ],
        }

    # ------------------------------------------------------------------ #
    # Верификация                                                        #
    # ------------------------------------------------------------------ #

    def verify_binding_token(
        self,
        db: Session,
        token: str,
        chat_id: str,
        telegram_user_id: str | None = None,
        username: str | None = None,
    ) -> dict[str, Any]:
        """Проверить токен и сохранить chat_id (encrypted/masked/hash); статус → verified."""
        token = (token or "").strip()
        chat_id = str(chat_id or "").strip()
        if not token or not chat_id:
            raise TelegramBindingError("Нужны token и chat_id")
        binding = telegram_repo.get_binding_by_verification_token_hash(db, _hash_token(token))
        if binding is None or binding.status not in ("pending_verification", "draft", "failed"):
            raise TelegramBindingError("Токен не найден или уже использован")
        if self._token_expired(binding):
            raise TelegramBindingError("Срок действия токена истёк — создайте новый")

        fields: dict[str, Any] = {
            "chat_id_encrypted": crm_secret_service.encrypt_secret(chat_id),
            "chat_id_masked": mask_chat_id(chat_id),
            "chat_id_hash": hash_chat_id(chat_id),
            "username": (username or None),
        }
        if telegram_user_id:
            tuid = str(telegram_user_id).strip()
            fields["telegram_user_id_encrypted"] = crm_secret_service.encrypt_secret(tuid)
            fields["telegram_user_id_masked"] = mask_chat_id(tuid)
            fields["telegram_user_id_hash"] = hash_chat_id(tuid)
        binding = telegram_repo.mark_verified(db, binding, _now(), **fields)
        self._write_audit(
            db,
            audit_actions.ACTION_TELEGRAM_BINDING_VERIFIED,
            account_id=binding.account_id,
            project_id=binding.project_id,
            user_id=binding.user_id,
            metadata={"binding_id": binding.id, "chat_id_masked": binding.chat_id_masked},
        )
        return telegram_repo.public_binding_view(binding)

    def verify_binding_from_update(
        self, db: Session, update_payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Разобрать Telegram-update (``/start <token>``) и верифицировать. БЕЗ сети (локально).

        Формат payload — как у Telegram Bot API update; парсим message.text и message.chat.id.
        В MVP реального polling/webhook нет — это скелет для будущего.
        """
        message = (update_payload or {}).get("message") or {}
        text = str(message.get("text") or "").strip()
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        chat_id = str(chat.get("id") or "").strip()
        token = ""
        if text.startswith("/start"):
            parts = text.split(maxsplit=1)
            token = parts[1].strip() if len(parts) > 1 else ""
        if not token or not chat_id:
            raise TelegramBindingError("В update нет /start <token> или chat.id")
        return self.verify_binding_token(
            db,
            token,
            chat_id,
            telegram_user_id=str(sender.get("id") or "") or None,
            username=sender.get("username"),
        )

    # ------------------------------------------------------------------ #
    # Управление                                                         #
    # ------------------------------------------------------------------ #

    def list_bindings(
        self, db: Session, user_id: int | None = None, project_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Список привязок (public view) по пользователю или проекту."""
        if project_id is not None:
            rows = telegram_repo.list_bindings_for_project(db, project_id)
        elif user_id is not None:
            rows = telegram_repo.list_bindings_for_user(db, user_id)
        else:
            rows = []
        return [telegram_repo.public_binding_view(r) for r in rows]

    def get_binding_for_user(
        self, db: Session, binding_id: int, current_user_id: int | None
    ) -> NotificationTelegramBinding:
        """Получить привязку с проверкой владельца (иначе ошибка)."""
        binding = telegram_repo.get_binding_by_id(db, binding_id)
        if binding is None:
            raise TelegramBindingError("Привязка не найдена")
        if current_user_id is not None and binding.user_id != current_user_id:
            raise TelegramBindingError("Нет доступа к привязке")
        return binding

    def disable_binding(
        self, db: Session, binding_id: int, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """Отключить привязку (disabled)."""
        binding = self.get_binding_for_user(db, binding_id, current_user_id)
        binding = telegram_repo.mark_disabled(db, binding, _now())
        self._write_audit(
            db,
            audit_actions.ACTION_TELEGRAM_BINDING_DISABLED,
            account_id=binding.account_id,
            project_id=binding.project_id,
            user_id=binding.user_id,
            metadata={"binding_id": binding.id},
        )
        return telegram_repo.public_binding_view(binding)

    def revoke_binding(
        self, db: Session, binding_id: int, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """Отозвать привязку (revoked); хранимый chat_id обнуляется."""
        binding = self.get_binding_for_user(db, binding_id, current_user_id)
        binding = telegram_repo.mark_revoked(db, binding, _now())
        self._write_audit(
            db,
            audit_actions.ACTION_TELEGRAM_BINDING_REVOKED,
            account_id=binding.account_id,
            project_id=binding.project_id,
            user_id=binding.user_id,
            metadata={"binding_id": binding.id},
        )
        return telegram_repo.public_binding_view(binding)

    # ------------------------------------------------------------------ #
    # Доставка (внутренний путь)                                         #
    # ------------------------------------------------------------------ #

    def get_active_binding(
        self, db: Session, user_id: int, project_id: int | None = None
    ) -> NotificationTelegramBinding | None:
        """Верифицированная привязка пользователя (или None)."""
        return telegram_repo.get_active_binding_for_user(db, user_id, project_id)

    def get_delivery_destination(
        self, db: Session, user_id: int, project_id: int | None = None
    ) -> str | None:
        """Расшифрованный chat_id для доставки — ТОЛЬКО внутри сервис/provider-пути (не наружу)."""
        binding = self.get_active_binding(db, user_id, project_id)
        if binding is None or not binding.chat_id_encrypted:
            return None
        try:
            return crm_secret_service.decrypt_secret(binding.chat_id_encrypted)
        except Exception:  # noqa: BLE001 — не роняем доставку из-за проблемы расшифровки
            logger.warning("telegram chat_id decrypt failed for binding_id=%s", binding.id)
            return None

    # ------------------------------------------------------------------ #
    # Внутреннее                                                         #
    # ------------------------------------------------------------------ #

    def _find_reusable_binding(
        self, db: Session, user_id: int, account_id: int | None, project_id: int | None
    ) -> NotificationTelegramBinding | None:
        for row in telegram_repo.list_bindings_for_user(db, user_id):
            if (
                row.project_id == project_id
                and row.account_id == account_id
                and row.status in ("draft", "pending_verification", "failed")
            ):
                return row
        return None

    def _token_expired(self, binding: NotificationTelegramBinding) -> bool:
        created = binding.created_at
        if created is None:
            return False
        ttl = self._resolve_settings().notification_telegram_binding_token_ttl_seconds
        # created_at может быть naive (SQLite) — сравниваем аккуратно.
        reference = created if created.tzinfo is not None else created.replace(tzinfo=UTC)
        return _now() > reference + timedelta(seconds=ttl)

    def _binding_enabled(self) -> bool:
        return bool(self._resolve_settings().notification_telegram_binding_enabled_effective)

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
        self,
        db: Session,
        action: str,
        account_id: int | None = None,
        project_id: int | None = None,
        user_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._audit_svc().record(
            db,
            action,
            account_id=account_id,
            project_id=project_id,
            user_id=user_id,
            entity_type="telegram_binding",
            metadata=metadata or {},
        )


def get_notification_telegram_binding_service() -> NotificationTelegramBindingService:
    """DI-фабрика сервиса привязок Telegram."""
    return NotificationTelegramBindingService()
