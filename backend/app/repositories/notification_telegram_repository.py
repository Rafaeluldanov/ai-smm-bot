"""Репозиторий привязок Telegram-канала уведомлений — v0.5.4.

Изолирует доступ к ``notification_telegram_bindings``. Публичное представление (``public_*``)
НИКОГДА не содержит сырой chat_id / telegram_user_id / verification token / bot token. Tenant
isolation обеспечивается на сервисном/API-слое.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.notification_telegram_binding import NotificationTelegramBinding

# Статусы, при которых binding считается «активной» для доставки.
_ACTIVE_STATUSES = ("verified",)


def create_binding(db: Session, **fields: Any) -> NotificationTelegramBinding:
    """Создать привязку Telegram (без сырых секретов в полях)."""
    binding = NotificationTelegramBinding(**fields)
    db.add(binding)
    db.commit()
    db.refresh(binding)
    return binding


def get_binding_by_id(db: Session, binding_id: int) -> NotificationTelegramBinding | None:
    """Привязка по id (или None)."""
    return db.get(NotificationTelegramBinding, binding_id)


def get_active_binding_for_user(
    db: Session, user_id: int, project_id: int | None = None
) -> NotificationTelegramBinding | None:
    """Верифицированная привязка пользователя (проектная приоритетнее глобальной)."""
    stmt = (
        select(NotificationTelegramBinding)
        .where(
            NotificationTelegramBinding.user_id == user_id,
            NotificationTelegramBinding.status.in_(_ACTIVE_STATUSES),
        )
        .order_by(NotificationTelegramBinding.id.desc())
    )
    rows = list(db.execute(stmt).scalars().all())
    if project_id is not None:
        for row in rows:
            if row.project_id == project_id:
                return row
    for row in rows:
        if row.project_id is None:
            return row
    return rows[0] if rows else None


def get_binding_by_verification_token_hash(
    db: Session, token_hash: str
) -> NotificationTelegramBinding | None:
    """Привязка по hash verification-токена (для верификации /start)."""
    stmt = select(NotificationTelegramBinding).where(
        NotificationTelegramBinding.verification_token_hash == token_hash
    )
    return db.execute(stmt).scalars().first()


def list_bindings_for_user(
    db: Session, user_id: int, limit: int = 100
) -> list[NotificationTelegramBinding]:
    """Привязки пользователя (свежие первыми)."""
    stmt = (
        select(NotificationTelegramBinding)
        .where(NotificationTelegramBinding.user_id == user_id)
        .order_by(NotificationTelegramBinding.id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def list_bindings_for_project(
    db: Session, project_id: int, limit: int = 200
) -> list[NotificationTelegramBinding]:
    """Привязки проекта (свежие первыми)."""
    stmt = (
        select(NotificationTelegramBinding)
        .where(NotificationTelegramBinding.project_id == project_id)
        .order_by(NotificationTelegramBinding.id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def update_binding(
    db: Session, binding: NotificationTelegramBinding, **fields: Any
) -> NotificationTelegramBinding:
    """Обновить произвольные поля привязки."""
    for key, value in fields.items():
        setattr(binding, key, value)
    db.commit()
    db.refresh(binding)
    return binding


def mark_pending(
    db: Session, binding: NotificationTelegramBinding, token_hash: str, token_prefix: str
) -> NotificationTelegramBinding:
    """Перевести привязку в pending_verification с новым token hash/prefix."""
    binding.status = "pending_verification"
    binding.verification_token_hash = token_hash
    binding.verification_token_prefix = token_prefix
    binding.verified_at = None
    db.commit()
    db.refresh(binding)
    return binding


def mark_verified(
    db: Session, binding: NotificationTelegramBinding, now: datetime, **fields: Any
) -> NotificationTelegramBinding:
    """Отметить привязку verified (chat_id/telegram_user_id уже encrypted в fields)."""
    binding.status = "verified"
    binding.verified_at = now
    binding.last_error = None
    binding.verification_token_hash = None
    binding.verification_token_prefix = None
    for key, value in fields.items():
        setattr(binding, key, value)
    db.commit()
    db.refresh(binding)
    return binding


def mark_disabled(
    db: Session, binding: NotificationTelegramBinding, now: datetime
) -> NotificationTelegramBinding:
    """Отключить привязку (disabled)."""
    binding.status = "disabled"
    binding.disabled_at = now
    db.commit()
    db.refresh(binding)
    return binding


def mark_revoked(
    db: Session, binding: NotificationTelegramBinding, now: datetime
) -> NotificationTelegramBinding:
    """Отозвать привязку (revoked); хранимые секреты обнуляются."""
    binding.status = "revoked"
    binding.revoked_at = now
    binding.chat_id_encrypted = None
    binding.telegram_user_id_encrypted = None
    binding.verification_token_hash = None
    binding.verification_token_prefix = None
    db.commit()
    db.refresh(binding)
    return binding


def record_delivery_success(
    db: Session, binding: NotificationTelegramBinding, now: datetime
) -> NotificationTelegramBinding:
    """Зафиксировать успешную доставку (сбрасывает счётчик ошибок)."""
    binding.last_delivery_at = now
    binding.failure_count = 0
    binding.last_error = None
    db.commit()
    db.refresh(binding)
    return binding


def record_delivery_failure(
    db: Session, binding: NotificationTelegramBinding, error: str | None
) -> NotificationTelegramBinding:
    """Зафиксировать сбой доставки (инкремент счётчика; текст ошибки уже санитизирован)."""
    binding.failure_count = int(binding.failure_count or 0) + 1
    binding.last_error = (error or "")[:512] or None
    db.commit()
    db.refresh(binding)
    return binding


def public_binding_view(binding: NotificationTelegramBinding) -> dict[str, Any]:
    """Безопасное представление привязки (без сырого chat_id / токена / bot token)."""
    return {
        "id": binding.id,
        "account_id": binding.account_id,
        "project_id": binding.project_id,
        "user_id": binding.user_id,
        "status": binding.status,
        "title": binding.title,
        "chat_id_masked": binding.chat_id_masked,
        "telegram_user_id_masked": binding.telegram_user_id_masked,
        "username": binding.username,
        "verification_token_prefix": binding.verification_token_prefix,
        "verified": binding.status == "verified",
        "verified_at": binding.verified_at.isoformat() if binding.verified_at else None,
        "last_delivery_at": (
            binding.last_delivery_at.isoformat() if binding.last_delivery_at else None
        ),
        "failure_count": binding.failure_count,
        "last_error": binding.last_error,
        "created_at": binding.created_at.isoformat() if binding.created_at else None,
    }
