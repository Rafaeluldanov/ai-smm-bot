"""Репозиторий доставки уведомлений и дайджестов (v0.5.1).

Хранит журнал доставки (``notification_delivery_logs``) и дайджесты (``notification_digests``).
Секретов/токенов/внутренних путей не содержит (санитизация — на сервисном слое; destination
только masked). Изоляция (recipient/project/account) обеспечивается сервисом/API. Физического
удаления нет — только смена статуса.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.notification_delivery_log import NotificationDeliveryLog
from app.models.notification_digest import NotificationDigest
from app.models.notification_preference import NotificationPreference

_RETRYABLE_STATUSES = ("pending", "retry_scheduled", "failed")


def _now() -> datetime:
    return datetime.now(UTC)


# --- Журнал доставки --- #


def create_delivery_log(db: Session, **fields: Any) -> NotificationDeliveryLog:
    """Создать запись доставки (destination уже маскирован, метаданные санитизированы)."""
    log = NotificationDeliveryLog(**fields)
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def get_delivery_log_by_id(db: Session, delivery_log_id: int) -> NotificationDeliveryLog | None:
    """Запись доставки по id (или None)."""
    return db.get(NotificationDeliveryLog, delivery_log_id)


def list_delivery_logs_for_user(
    db: Session,
    recipient_user_id: int,
    status: str | None = None,
    channel: str | None = None,
    provider: str | None = None,
    project_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[NotificationDeliveryLog]:
    """Логи доставки пользователя (свежие первыми) с фильтрами."""
    stmt = select(NotificationDeliveryLog).where(
        NotificationDeliveryLog.recipient_user_id == recipient_user_id
    )
    if status is not None:
        stmt = stmt.where(NotificationDeliveryLog.status == status)
    if channel is not None:
        stmt = stmt.where(NotificationDeliveryLog.channel == channel)
    if provider is not None:
        stmt = stmt.where(NotificationDeliveryLog.provider == provider)
    if project_id is not None:
        stmt = stmt.where(NotificationDeliveryLog.project_id == project_id)
    stmt = stmt.order_by(NotificationDeliveryLog.id.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def list_delivery_logs_for_project(
    db: Session, project_id: int, status: str | None = None, limit: int = 200
) -> list[NotificationDeliveryLog]:
    """Логи доставки проекта (для дашборда)."""
    stmt = select(NotificationDeliveryLog).where(NotificationDeliveryLog.project_id == project_id)
    if status is not None:
        stmt = stmt.where(NotificationDeliveryLog.status == status)
    stmt = stmt.order_by(NotificationDeliveryLog.id.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def list_pending_delivery_logs(
    db: Session, ref: datetime | None = None, limit: int = 100
) -> list[NotificationDeliveryLog]:
    """Логи, ожидающие (повторной) доставки: pending/retry_scheduled с наступившим next_retry_at."""
    reference = ref or _now()
    stmt = (
        select(NotificationDeliveryLog)
        .where(
            NotificationDeliveryLog.status.in_(("pending", "retry_scheduled")),
            (NotificationDeliveryLog.next_retry_at.is_(None))
            | (NotificationDeliveryLog.next_retry_at <= reference),
        )
        .order_by(NotificationDeliveryLog.id.asc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def mark_sent(
    db: Session,
    log: NotificationDeliveryLog,
    provider_message_id: str | None = None,
    response_metadata: dict[str, Any] | None = None,
) -> NotificationDeliveryLog:
    """Отметить доставку успешной (в MVP — mock: лог без реальной отправки)."""
    log.status = "sent"
    log.attempts = (log.attempts or 0) + 1
    log.sent_at = _now()
    log.next_retry_at = None
    log.error_message = None
    if provider_message_id is not None:
        log.provider_message_id = provider_message_id
    if response_metadata is not None:
        log.response_metadata = response_metadata
    db.commit()
    db.refresh(log)
    return log


def mark_failed(
    db: Session,
    log: NotificationDeliveryLog,
    error_message: str | None = None,
    response_metadata: dict[str, Any] | None = None,
) -> NotificationDeliveryLog:
    """Отметить доставку неуспешной (ошибка санитизирована на сервисном слое)."""
    log.status = "failed"
    log.attempts = (log.attempts or 0) + 1
    log.failed_at = _now()
    if error_message is not None:
        log.error_message = error_message[:512]
    if response_metadata is not None:
        log.response_metadata = response_metadata
    db.commit()
    db.refresh(log)
    return log


def mark_skipped(
    db: Session, log: NotificationDeliveryLog, error_message: str | None = None
) -> NotificationDeliveryLog:
    """Отметить доставку пропущенной (напр. dry-run/предпочтения)."""
    log.status = "skipped"
    if error_message is not None:
        log.error_message = error_message[:512]
    db.commit()
    db.refresh(log)
    return log


def mark_disabled(
    db: Session, log: NotificationDeliveryLog, error_message: str | None = None
) -> NotificationDeliveryLog:
    """Отметить доставку отключённой (внешняя доставка/канал выключены)."""
    log.status = "disabled"
    if error_message is not None:
        log.error_message = error_message[:512]
    db.commit()
    db.refresh(log)
    return log


def schedule_retry(
    db: Session,
    log: NotificationDeliveryLog,
    backoff_seconds: int,
    error_message: str | None = None,
) -> NotificationDeliveryLog:
    """Запланировать повтор с backoff (increment attempts)."""
    log.status = "retry_scheduled"
    log.attempts = (log.attempts or 0) + 1
    log.next_retry_at = _now() + timedelta(seconds=max(1, backoff_seconds))
    if error_message is not None:
        log.error_message = error_message[:512]
    db.commit()
    db.refresh(log)
    return log


def get_delivery_dashboard_summary(
    db: Session, project_id: int | None = None, user_id: int | None = None
) -> dict[str, Any]:
    """Агрегаты доставки: по статусу/каналу/провайдеру."""
    stmt = select(NotificationDeliveryLog)
    if project_id is not None:
        stmt = stmt.where(NotificationDeliveryLog.project_id == project_id)
    if user_id is not None:
        stmt = stmt.where(NotificationDeliveryLog.recipient_user_id == user_id)
    logs = list(db.scalars(stmt.limit(5000)).all())
    by_status: dict[str, int] = {}
    by_channel: dict[str, int] = {}
    by_provider: dict[str, int] = {}
    for log in logs:
        by_status[log.status] = by_status.get(log.status, 0) + 1
        by_channel[log.channel] = by_channel.get(log.channel, 0) + 1
        by_provider[log.provider] = by_provider.get(log.provider, 0) + 1
    return {
        "total": len(logs),
        "by_status": by_status,
        "by_channel": by_channel,
        "by_provider": by_provider,
    }


# --- Дайджесты --- #


def create_digest(db: Session, **fields: Any) -> NotificationDigest:
    """Создать дайджест (subject/body_preview санитизированы сервисом)."""
    digest = NotificationDigest(**fields)
    db.add(digest)
    db.commit()
    db.refresh(digest)
    return digest


def get_digest_by_id(db: Session, digest_id: int) -> NotificationDigest | None:
    """Дайджест по id (или None)."""
    return db.get(NotificationDigest, digest_id)


def list_digests_for_user(
    db: Session, user_id: int, status: str | None = None, limit: int = 100
) -> list[NotificationDigest]:
    """Дайджесты пользователя (свежие первыми)."""
    stmt = select(NotificationDigest).where(NotificationDigest.user_id == user_id)
    if status is not None:
        stmt = stmt.where(NotificationDigest.status == status)
    stmt = stmt.order_by(NotificationDigest.id.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def list_digests_for_project(
    db: Session, project_id: int, limit: int = 200
) -> list[NotificationDigest]:
    """Дайджесты проекта (для дашборда)."""
    stmt = (
        select(NotificationDigest)
        .where(NotificationDigest.project_id == project_id)
        .order_by(NotificationDigest.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def list_pending_digests(
    db: Session, frequency: str | None = None, limit: int = 100
) -> list[NotificationDigest]:
    """Дайджесты в статусе draft/generated (ожидают отправки)."""
    stmt = select(NotificationDigest).where(NotificationDigest.status.in_(("draft", "generated")))
    if frequency is not None:
        stmt = stmt.where(NotificationDigest.frequency == frequency)
    stmt = stmt.order_by(NotificationDigest.id.asc()).limit(limit)
    return list(db.scalars(stmt).all())


def mark_digest_generated(db: Session, digest: NotificationDigest) -> NotificationDigest:
    """Отметить дайджест сгенерированным."""
    digest.status = "generated"
    digest.generated_at = _now()
    db.commit()
    db.refresh(digest)
    return digest


def mark_digest_sent(
    db: Session, digest: NotificationDigest, delivery_log_id: int | None = None
) -> NotificationDigest:
    """Отметить дайджест отправленным (в MVP — mock)."""
    digest.status = "sent"
    digest.sent_at = _now()
    if delivery_log_id is not None:
        digest.delivery_log_id = delivery_log_id
    db.commit()
    db.refresh(digest)
    return digest


def mark_digest_skipped(db: Session, digest: NotificationDigest) -> NotificationDigest:
    """Отметить дайджест пропущенным."""
    digest.status = "skipped"
    db.commit()
    db.refresh(digest)
    return digest


def mark_digest_failed(
    db: Session, digest: NotificationDigest, error_message: str | None = None
) -> NotificationDigest:
    """Отметить дайджест ошибочным (ошибка санитизирована)."""
    digest.status = "failed"
    if error_message is not None:
        digest.error_message = error_message[:512]
    db.commit()
    db.refresh(digest)
    return digest


def list_digest_user_ids(db: Session, frequency: str | None = None, limit: int = 500) -> list[int]:
    """Пользователи с включённой настройкой дайджеста (channel=digest, enabled=true)."""
    stmt = select(NotificationPreference.user_id).where(
        NotificationPreference.channel == "digest",
        NotificationPreference.enabled.is_(True),
    )
    if frequency is not None:
        stmt = stmt.where(NotificationPreference.digest_frequency == frequency)
    stmt = stmt.distinct().limit(limit)
    return [int(uid) for uid in db.scalars(stmt).all()]


def count_delivery_by_status(db: Session, user_id: int) -> int:
    """Число delivery-логов пользователя (для инфо)."""
    stmt = (
        select(func.count())
        .select_from(NotificationDeliveryLog)
        .where(NotificationDeliveryLog.recipient_user_id == user_id)
    )
    return int(db.scalar(stmt) or 0)
