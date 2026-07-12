"""Репозиторий внутренних уведомлений, упоминаний и настроек (v0.5.0).

Хранит in-app уведомления (``app_notifications``), упоминания (``app_mentions``) и настройки
(``notification_preferences``). Тексты/метаданные секретов и внутренних путей не содержат
(санитизация — на сервисном слое). Изоляция (recipient/project/account) обеспечивается
сервисом/API. Физического удаления нет — только смена статуса.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.app_mention import AppMention
from app.models.app_notification import AppNotification
from app.models.notification_preference import NotificationPreference

_ACTIVE_STATUSES = ("unread", "read")


def _now() -> datetime:
    return datetime.now(UTC)


# --- Уведомления --- #


def create_notification(db: Session, **fields: Any) -> AppNotification:
    """Создать уведомление (тексты/метаданные должны быть уже санитизированы сервисом)."""
    notification = AppNotification(**fields)
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification


def get_notification_by_id(db: Session, notification_id: int) -> AppNotification | None:
    """Уведомление по id (или None)."""
    return db.get(AppNotification, notification_id)


def list_for_user(
    db: Session,
    recipient_user_id: int,
    status: str | None = None,
    notification_type: str | None = None,
    priority: str | None = None,
    project_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AppNotification]:
    """Уведомления пользователя (свежие первыми) с фильтрами."""
    stmt = select(AppNotification).where(AppNotification.recipient_user_id == recipient_user_id)
    if status is not None:
        stmt = stmt.where(AppNotification.status == status)
    if notification_type is not None:
        stmt = stmt.where(AppNotification.notification_type == notification_type)
    if priority is not None:
        stmt = stmt.where(AppNotification.priority == priority)
    if project_id is not None:
        stmt = stmt.where(AppNotification.project_id == project_id)
    stmt = stmt.order_by(AppNotification.id.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def list_unread_for_user(
    db: Session, recipient_user_id: int, limit: int = 50
) -> list[AppNotification]:
    """Непрочитанные уведомления пользователя."""
    return list_for_user(db, recipient_user_id, status="unread", limit=limit)


def count_unread_for_user(db: Session, recipient_user_id: int) -> int:
    """Число непрочитанных уведомлений пользователя."""
    stmt = (
        select(func.count())
        .select_from(AppNotification)
        .where(
            AppNotification.recipient_user_id == recipient_user_id,
            AppNotification.status == "unread",
        )
    )
    return int(db.scalar(stmt) or 0)


def mark_read(db: Session, notification: AppNotification) -> AppNotification:
    """Отметить уведомление прочитанным."""
    if notification.status == "unread":
        notification.status = "read"
        notification.read_at = _now()
        db.commit()
        db.refresh(notification)
    return notification


def mark_all_read(db: Session, recipient_user_id: int, project_id: int | None = None) -> int:
    """Отметить все непрочитанные уведомления пользователя прочитанными; вернуть число."""
    stmt = select(AppNotification).where(
        AppNotification.recipient_user_id == recipient_user_id,
        AppNotification.status == "unread",
    )
    if project_id is not None:
        stmt = stmt.where(AppNotification.project_id == project_id)
    now = _now()
    count = 0
    for notification in db.scalars(stmt).all():
        notification.status = "read"
        notification.read_at = now
        count += 1
    if count:
        db.commit()
    return count


def dismiss_notification(db: Session, notification: AppNotification) -> AppNotification:
    """Скрыть (dismiss) уведомление."""
    notification.status = "dismissed"
    notification.dismissed_at = _now()
    if notification.read_at is None:
        notification.read_at = _now()
    db.commit()
    db.refresh(notification)
    return notification


def archive_notification(db: Session, notification: AppNotification) -> AppNotification:
    """Архивировать уведомление."""
    notification.status = "archived"
    notification.archived_at = _now()
    db.commit()
    db.refresh(notification)
    return notification


def list_for_project(
    db: Session,
    project_id: int,
    status: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[AppNotification]:
    """Уведомления проекта (для дашборда проекта)."""
    stmt = select(AppNotification).where(AppNotification.project_id == project_id)
    if status is not None:
        stmt = stmt.where(AppNotification.status == status)
    stmt = stmt.order_by(AppNotification.id.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def list_due_notifications(
    db: Session, ref: datetime | None = None, limit: int = 200
) -> list[AppNotification]:
    """Уведомления с наступившим due_at (активные)."""
    reference = ref or _now()
    stmt = (
        select(AppNotification)
        .where(
            AppNotification.due_at.is_not(None),
            AppNotification.due_at < reference,
            AppNotification.status.in_(_ACTIVE_STATUSES),
        )
        .order_by(AppNotification.due_at.asc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def find_duplicate_recent(
    db: Session,
    recipient_user_id: int | None,
    notification_type: str,
    entity_type: str | None,
    entity_id: str | None,
    since: datetime,
) -> AppNotification | None:
    """Найти недавнее непрочитанное уведомление того же типа/сущности (для дедупликации)."""
    stmt = select(AppNotification).where(
        AppNotification.recipient_user_id == recipient_user_id,
        AppNotification.notification_type == notification_type,
        AppNotification.status == "unread",
        AppNotification.created_at >= since,
    )
    if entity_type is not None:
        stmt = stmt.where(AppNotification.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(AppNotification.entity_id == entity_id)
    stmt = stmt.order_by(AppNotification.id.desc())
    return db.scalars(stmt).first()


def prune_over_limit(db: Session, recipient_user_id: int, max_per_user: int) -> int:
    """Заархивировать самые старые уведомления сверх лимита на пользователя; вернуть число."""
    stmt = (
        select(AppNotification)
        .where(
            AppNotification.recipient_user_id == recipient_user_id,
            AppNotification.status.in_(_ACTIVE_STATUSES),
        )
        .order_by(AppNotification.id.desc())
        .offset(max_per_user)
    )
    now = _now()
    count = 0
    for notification in db.scalars(stmt).all():
        notification.status = "archived"
        notification.archived_at = now
        count += 1
    if count:
        db.commit()
    return count


# --- Упоминания --- #


def create_mention(db: Session, **fields: Any) -> AppMention:
    """Создать упоминание (текст санитизирован сервисом)."""
    mention = AppMention(**fields)
    db.add(mention)
    db.commit()
    db.refresh(mention)
    return mention


def list_mentions_for_entity(
    db: Session, source_entity_type: str, source_entity_id: str, limit: int = 200
) -> list[AppMention]:
    """Упоминания в сущности."""
    stmt = (
        select(AppMention)
        .where(
            AppMention.source_entity_type == source_entity_type,
            AppMention.source_entity_id == source_entity_id,
        )
        .order_by(AppMention.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def list_mentions_for_user(
    db: Session, mentioned_user_id: int, limit: int = 200
) -> list[AppMention]:
    """Упоминания пользователя."""
    stmt = (
        select(AppMention)
        .where(AppMention.mentioned_user_id == mentioned_user_id)
        .order_by(AppMention.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def list_mentions_for_project(
    db: Session, project_id: int, status: str | None = None, limit: int = 200
) -> list[AppMention]:
    """Упоминания проекта (для дашборда)."""
    stmt = select(AppMention).where(AppMention.project_id == project_id)
    if status is not None:
        stmt = stmt.where(AppMention.status == status)
    stmt = stmt.order_by(AppMention.id.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def resolve_mention(
    db: Session,
    mention: AppMention,
    mentioned_user_id: int | None,
    status: str,
    notification_id: int | None = None,
) -> AppMention:
    """Обновить упоминание: пользователь/статус/связанное уведомление."""
    mention.mentioned_user_id = mentioned_user_id
    mention.status = status
    if notification_id is not None:
        mention.notification_id = notification_id
    if status in ("resolved", "notified"):
        mention.resolved_at = _now()
    db.commit()
    db.refresh(mention)
    return mention


# --- Настройки уведомлений --- #


def get_preferences(
    db: Session, user_id: int, account_id: int | None = None
) -> list[NotificationPreference]:
    """Настройки уведомлений пользователя."""
    stmt = select(NotificationPreference).where(NotificationPreference.user_id == user_id)
    if account_id is not None:
        stmt = stmt.where(NotificationPreference.account_id == account_id)
    stmt = stmt.order_by(NotificationPreference.id)
    return list(db.scalars(stmt).all())


def get_preference(
    db: Session,
    user_id: int,
    channel: str,
    notification_type: str | None,
    account_id: int | None = None,
) -> NotificationPreference | None:
    """Одна настройка по (user, channel, type, account) или None."""
    stmt = select(NotificationPreference).where(
        NotificationPreference.user_id == user_id,
        NotificationPreference.channel == channel,
        NotificationPreference.notification_type.is_(None)
        if notification_type is None
        else NotificationPreference.notification_type == notification_type,
    )
    if account_id is not None:
        stmt = stmt.where(NotificationPreference.account_id == account_id)
    return db.scalars(stmt).first()


def set_preference(
    db: Session,
    user_id: int,
    channel: str,
    enabled: bool,
    notification_type: str | None = None,
    account_id: int | None = None,
    digest_frequency: str | None = None,
) -> NotificationPreference:
    """Upsert настройки уведомления по (user, channel, type)."""
    pref = get_preference(db, user_id, channel, notification_type, account_id)
    if pref is None:
        pref = NotificationPreference(
            user_id=user_id,
            account_id=account_id,
            channel=channel,
            notification_type=notification_type,
            enabled=enabled,
            digest_frequency=digest_frequency,
        )
        db.add(pref)
    else:
        pref.enabled = enabled
        if digest_frequency is not None:
            pref.digest_frequency = digest_frequency
    db.commit()
    db.refresh(pref)
    return pref


# --- Сводки --- #


def get_dashboard_summary(db: Session, project_id: int) -> dict[str, Any]:
    """Агрегаты уведомлений проекта: по статусу/типу/приоритету."""
    notifications = list_for_project(db, project_id, limit=2000)
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    for n in notifications:
        by_status[n.status] = by_status.get(n.status, 0) + 1
        by_type[n.notification_type] = by_type.get(n.notification_type, 0) + 1
        by_priority[n.priority] = by_priority.get(n.priority, 0) + 1
    return {
        "total": len(notifications),
        "by_status": by_status,
        "by_type": by_type,
        "by_priority": by_priority,
    }
