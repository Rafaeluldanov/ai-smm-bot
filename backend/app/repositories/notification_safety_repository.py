"""Репозиторий safety-слоя уведомлений (v0.5.2): opt-out, suppression, rate-limit, webhooks.

Секретов/сырых адресов/URL в публичных выборках нет (только masked/hash). Изоляция
(user/project/account) обеспечивается сервисом/API. Физического удаления нет — смена статуса.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.notification_opt_out import NotificationOptOut
from app.models.notification_rate_limit_bucket import NotificationRateLimitBucket
from app.models.notification_suppression import NotificationSuppression
from app.models.webhook_subscription import WebhookSubscription


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


# ------------------------------------------------------------------ #
# Opt-out                                                            #
# ------------------------------------------------------------------ #


def create_opt_out(db: Session, **fields: Any) -> NotificationOptOut:
    """Создать активную отписку."""
    opt_out = NotificationOptOut(**fields)
    db.add(opt_out)
    db.commit()
    db.refresh(opt_out)
    return opt_out


def get_opt_out_by_id(db: Session, opt_out_id: int) -> NotificationOptOut | None:
    """Отписка по id (или None)."""
    return db.get(NotificationOptOut, opt_out_id)


def list_opt_outs_for_user(
    db: Session, user_id: int, status: str = "active", limit: int = 200
) -> list[NotificationOptOut]:
    """Отписки пользователя."""
    stmt = select(NotificationOptOut).where(NotificationOptOut.user_id == user_id)
    if status is not None:
        stmt = stmt.where(NotificationOptOut.status == status)
    stmt = stmt.order_by(NotificationOptOut.id.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def list_opt_outs_for_project(
    db: Session, project_id: int, limit: int = 200
) -> list[NotificationOptOut]:
    """Отписки, привязанные к проекту."""
    stmt = (
        select(NotificationOptOut)
        .where(NotificationOptOut.project_id == project_id)
        .order_by(NotificationOptOut.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def is_opted_out(
    db: Session,
    user_id: int,
    channel: str | None = None,
    notification_type: str | None = None,
    project_id: int | None = None,
    account_id: int | None = None,
) -> NotificationOptOut | None:
    """Есть ли активная отписка, применимая к (channel, type, project, account). Возвращает её."""
    stmt = select(NotificationOptOut).where(
        NotificationOptOut.user_id == user_id,
        NotificationOptOut.status == "active",
    )
    for opt in db.scalars(stmt).all():
        if opt.scope == "global":
            return opt
        if opt.scope == "account" and account_id is not None and opt.account_id == account_id:
            return opt
        if opt.scope == "project" and project_id is not None and opt.project_id == project_id:
            return opt
        if opt.scope == "channel" and channel is not None and opt.channel == channel:
            return opt
        if (
            opt.scope == "notification_type"
            and notification_type is not None
            and opt.notification_type == notification_type
        ):
            return opt
    return None


def revoke_opt_out(
    db: Session, opt_out: NotificationOptOut, current_user_id: int | None = None
) -> NotificationOptOut:
    """Отменить отписку (снова разрешить доставку)."""
    opt_out.status = "revoked"
    opt_out.revoked_at = _now()
    opt_out.revoked_by_user_id = current_user_id
    db.commit()
    db.refresh(opt_out)
    return opt_out


# ------------------------------------------------------------------ #
# Suppression                                                         #
# ------------------------------------------------------------------ #


def _find_suppression_row(
    db: Session,
    user_id: int | None,
    channel: str,
    provider: str | None,
    destination_hash: str | None,
) -> NotificationSuppression | None:
    stmt = (
        select(NotificationSuppression)
        .where(
            NotificationSuppression.user_id == user_id,
            NotificationSuppression.channel == channel,
            NotificationSuppression.provider == provider,
            NotificationSuppression.destination_hash == destination_hash,
            NotificationSuppression.status != "cleared",
        )
        .order_by(NotificationSuppression.id.desc())
    )
    return db.scalars(stmt).first()


def is_suppressed(
    db: Session,
    user_id: int | None,
    channel: str,
    provider: str | None = None,
    destination_hash: str | None = None,
) -> NotificationSuppression | None:
    """Активное подавление канала/адреса (suppressed_until в будущем или None). Возвращает его."""
    row = _find_suppression_row(db, user_id, channel, provider, destination_hash)
    if row is None or row.status != "active":
        return None
    until = _aware(row.suppressed_until)
    if until is not None and until <= _now():
        return None  # истекло
    return row


def create_or_update_suppression(
    db: Session,
    user_id: int | None,
    channel: str,
    reason: str,
    provider: str | None = None,
    destination_hash: str | None = None,
    account_id: int | None = None,
    project_id: int | None = None,
    ttl_seconds: int | None = None,
) -> NotificationSuppression:
    """Создать/активировать подавление (напр. вручную admin)."""
    row = _find_suppression_row(db, user_id, channel, provider, destination_hash)
    now = _now()
    until = now + timedelta(seconds=ttl_seconds) if ttl_seconds else None
    if row is None:
        row = NotificationSuppression(
            account_id=account_id,
            project_id=project_id,
            user_id=user_id,
            channel=channel,
            provider=provider,
            destination_hash=destination_hash,
            reason=reason,
            status="active",
            suppressed_until=until,
        )
        db.add(row)
    else:
        row.status = "active"
        row.reason = reason
        row.suppressed_until = until
    db.commit()
    db.refresh(row)
    return row


def record_failure(
    db: Session,
    user_id: int | None,
    channel: str,
    threshold: int,
    ttl_seconds: int,
    provider: str | None = None,
    destination_hash: str | None = None,
    account_id: int | None = None,
    project_id: int | None = None,
) -> tuple[NotificationSuppression, bool]:
    """Зафиксировать ошибку доставки; при достижении порога — активировать подавление.

    Возвращает (suppression, activated_now).
    """
    row = _find_suppression_row(db, user_id, channel, provider, destination_hash)
    now = _now()
    if row is None:
        row = NotificationSuppression(
            account_id=account_id,
            project_id=project_id,
            user_id=user_id,
            channel=channel,
            provider=provider,
            destination_hash=destination_hash,
            reason="too_many_failures",
            status="pending",
            failure_count=0,
            first_failure_at=now,
        )
        db.add(row)
    row.failure_count = (row.failure_count or 0) + 1
    row.last_failure_at = now
    if row.first_failure_at is None:
        row.first_failure_at = now
    activated = False
    if row.failure_count >= threshold and row.status != "active":
        row.status = "active"
        row.reason = "too_many_failures"
        row.suppressed_until = now + timedelta(seconds=ttl_seconds)
        activated = True
    db.commit()
    db.refresh(row)
    return row, activated


def record_success(
    db: Session,
    user_id: int | None,
    channel: str,
    provider: str | None = None,
    destination_hash: str | None = None,
) -> NotificationSuppression | None:
    """Успех доставки: сбросить счётчик ошибок и снять активное подавление."""
    row = _find_suppression_row(db, user_id, channel, provider, destination_hash)
    if row is None:
        return None
    row.failure_count = 0
    if row.status == "active":
        row.status = "cleared"
        row.cleared_at = _now()
    db.commit()
    db.refresh(row)
    return row


def clear_suppression(
    db: Session, suppression: NotificationSuppression, current_user_id: int | None = None
) -> NotificationSuppression:
    """Вручную снять подавление."""
    suppression.status = "cleared"
    suppression.cleared_at = _now()
    suppression.cleared_by_user_id = current_user_id
    suppression.failure_count = 0
    db.commit()
    db.refresh(suppression)
    return suppression


def get_suppression_by_id(db: Session, suppression_id: int) -> NotificationSuppression | None:
    """Подавление по id (или None)."""
    return db.get(NotificationSuppression, suppression_id)


def list_suppressions(
    db: Session,
    user_id: int | None = None,
    project_id: int | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[NotificationSuppression]:
    """Подавления по пользователю/проекту/статусу."""
    stmt = select(NotificationSuppression)
    if user_id is not None:
        stmt = stmt.where(NotificationSuppression.user_id == user_id)
    if project_id is not None:
        stmt = stmt.where(NotificationSuppression.project_id == project_id)
    if status is not None:
        stmt = stmt.where(NotificationSuppression.status == status)
    stmt = stmt.order_by(NotificationSuppression.id.desc()).limit(limit)
    return list(db.scalars(stmt).all())


# ------------------------------------------------------------------ #
# Rate-limit                                                          #
# ------------------------------------------------------------------ #


def get_or_create_bucket(
    db: Session,
    bucket_key: str,
    window_seconds: int,
    limit_value: int,
    scope: str = "user",
    user_id: int | None = None,
    account_id: int | None = None,
    project_id: int | None = None,
    channel: str | None = None,
    provider: str | None = None,
    notification_type: str | None = None,
) -> NotificationRateLimitBucket:
    """Получить активный бакет по ключу; истёкший — сбросить; иначе создать."""
    now = _now()
    stmt = (
        select(NotificationRateLimitBucket)
        .where(NotificationRateLimitBucket.bucket_key == bucket_key)
        .order_by(NotificationRateLimitBucket.id.desc())
    )
    bucket = db.scalars(stmt).first()
    if bucket is not None:
        reset_at = _aware(bucket.reset_at)
        if reset_at is not None and reset_at <= now:
            bucket.window_start = now
            bucket.reset_at = now + timedelta(seconds=window_seconds)
            bucket.count = 0
            bucket.limit_value = limit_value
            bucket.window_seconds = window_seconds
            db.commit()
            db.refresh(bucket)
        return bucket
    bucket = NotificationRateLimitBucket(
        account_id=account_id,
        project_id=project_id,
        user_id=user_id,
        channel=channel,
        provider=provider,
        notification_type=notification_type,
        scope=scope,
        bucket_key=bucket_key,
        window_start=now,
        window_seconds=window_seconds,
        count=0,
        limit_value=limit_value,
        reset_at=now + timedelta(seconds=window_seconds),
    )
    db.add(bucket)
    db.commit()
    db.refresh(bucket)
    return bucket


def increment_bucket(
    db: Session, bucket: NotificationRateLimitBucket
) -> NotificationRateLimitBucket:
    """Увеличить счётчик бакета на 1."""
    bucket.count = (bucket.count or 0) + 1
    db.commit()
    db.refresh(bucket)
    return bucket


def reset_bucket(db: Session, bucket: NotificationRateLimitBucket) -> NotificationRateLimitBucket:
    """Сбросить бакет (новое окно)."""
    now = _now()
    bucket.window_start = now
    bucket.reset_at = now + timedelta(seconds=bucket.window_seconds or 3600)
    bucket.count = 0
    db.commit()
    db.refresh(bucket)
    return bucket


def list_buckets(
    db: Session, user_id: int | None = None, project_id: int | None = None, limit: int = 200
) -> list[NotificationRateLimitBucket]:
    """Активные бакеты пользователя/проекта."""
    stmt = select(NotificationRateLimitBucket)
    if user_id is not None:
        stmt = stmt.where(NotificationRateLimitBucket.user_id == user_id)
    if project_id is not None:
        stmt = stmt.where(NotificationRateLimitBucket.project_id == project_id)
    stmt = stmt.order_by(NotificationRateLimitBucket.id.desc()).limit(limit)
    return list(db.scalars(stmt).all())


# ------------------------------------------------------------------ #
# Webhook subscriptions                                              #
# ------------------------------------------------------------------ #


def create_webhook_subscription(db: Session, **fields: Any) -> WebhookSubscription:
    """Создать подписку webhook (URL/secret уже encrypted/masked сервисом)."""
    sub = WebhookSubscription(**fields)
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def get_webhook_subscription_by_id(db: Session, subscription_id: int) -> WebhookSubscription | None:
    """Подписка webhook по id (или None)."""
    return db.get(WebhookSubscription, subscription_id)


def list_webhook_subscriptions(
    db: Session,
    account_id: int | None = None,
    project_id: int | None = None,
    user_id: int | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[WebhookSubscription]:
    """Подписки webhook по аккаунту/проекту/пользователю/статусу."""
    stmt = select(WebhookSubscription)
    if account_id is not None:
        stmt = stmt.where(WebhookSubscription.account_id == account_id)
    if project_id is not None:
        stmt = stmt.where(WebhookSubscription.project_id == project_id)
    if user_id is not None:
        stmt = stmt.where(WebhookSubscription.user_id == user_id)
    if status is not None:
        stmt = stmt.where(WebhookSubscription.status == status)
    stmt = stmt.order_by(WebhookSubscription.id.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def update_webhook_subscription(
    db: Session, sub: WebhookSubscription, **fields: Any
) -> WebhookSubscription:
    """Обновить поля подписки."""
    for key, value in fields.items():
        setattr(sub, key, value)
    db.commit()
    db.refresh(sub)
    return sub


def revoke_webhook_subscription(
    db: Session, sub: WebhookSubscription, current_user_id: int | None = None
) -> WebhookSubscription:
    """Отозвать подписку webhook."""
    sub.status = "revoked"
    sub.revoked_at = _now()
    meta = dict(sub.subscription_metadata or {})
    if current_user_id is not None:
        meta["revoked_by_user_id"] = current_user_id
    sub.subscription_metadata = meta
    db.commit()
    db.refresh(sub)
    return sub


def record_webhook_delivery_result(
    db: Session,
    sub: WebhookSubscription,
    success: bool,
    error_message: str | None = None,
    suppress_threshold: int | None = None,
) -> WebhookSubscription:
    """Зафиксировать результат доставки webhook (успех/ошибка) без раскрытия секретов."""
    sub.last_delivery_at = _now()
    if success:
        sub.failure_count = 0
        sub.last_error = None
        if sub.status == "suppressed":
            sub.status = "active"
    else:
        sub.failure_count = (sub.failure_count or 0) + 1
        sub.last_error = (error_message or "delivery failed")[:512]
        if suppress_threshold is not None and sub.failure_count >= suppress_threshold:
            sub.status = "suppressed"
    db.commit()
    db.refresh(sub)
    return sub
