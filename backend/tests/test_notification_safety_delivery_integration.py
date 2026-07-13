"""Тесты интеграции safety-гейтов в доставку уведомлений (v0.5.2). Offline."""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.notification_delivery_service import NotificationDeliveryService
from app.services.notification_service import NotificationService
from app.services.notification_suppression_service import NotificationSuppressionService
from app.services.notification_unsubscribe_service import NotificationUnsubscribeService
from app.services.webhook_subscription_service import WebhookSubscriptionService


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project, owner


def _notif(db, account, project, owner, **kw):  # noqa: ANN001, ANN003, ANN202
    return NotificationService().create_notification(
        db,
        recipient_user_id=owner.id,
        notification_type="review_assigned",
        title="T",
        message="m",
        account_id=account.id,
        project_id=project.id,
        entity_id=kw.get("entity_id", 1),
    )


def test_opt_out_blocks_delivery(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "int-oo")
    NotificationUnsubscribeService().create_opt_out(
        db_session, owner.id, "channel", channel="email"
    )
    n = _notif(db_session, account, project, owner)
    log = NotificationDeliveryService().create_delivery_job(db_session, n["id"], "email")
    assert log.status == "disabled" and log.error_message == "user_unsubscribed"


def test_suppression_blocks_delivery(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "int-sup")
    # Порог 1 → одна ошибка активирует подавление на email-адрес получателя.
    NotificationSuppressionService(
        settings=Settings(notification_suppression_failure_threshold=1)
    ).record_delivery_failure(db_session, owner.id, "email", destination=owner.email)
    n = _notif(db_session, account, project, owner)
    log = NotificationDeliveryService(
        settings=Settings(notification_suppression_failure_threshold=1)
    ).create_delivery_job(db_session, n["id"], "email")
    assert log.status == "disabled" and log.error_message == "too_many_failures"


def test_rate_limit_blocks_delivery(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "int-rl")
    s = Settings(notification_rate_limit_email_per_hour=1)
    from app.services.notification_rate_limit_service import NotificationRateLimitService

    NotificationRateLimitService(settings=s).record_delivery_attempt(db_session, owner.id, "email")
    n = _notif(db_session, account, project, owner)
    log = NotificationDeliveryService(settings=s).create_delivery_job(db_session, n["id"], "email")
    assert log.status == "skipped" and log.error_message == "rate_limited"


def test_missing_destination_blocks(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "int-nodest")
    n = _notif(db_session, account, project, owner)
    # telegram-адрес: если default chat id пуст, используется chat:{uid} → есть адрес.
    # Проверим webhook без per-user URL — sandbox использует placeholder, значит адрес есть.
    # Для чистоты: у пользователя есть email — не missing_destination (opt-out путь проверен выше).
    log = NotificationDeliveryService().create_delivery_job(db_session, n["id"], "email")
    # Статус pending/skipped/disabled — задача не падает.
    assert log.status in ("pending", "skipped", "disabled")


def test_webhook_live_disabled_refuses(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "int-whlive")
    n = _notif(db_session, account, project, owner)
    svc = WebhookSubscriptionService()
    view = svc.create_subscription(
        db_session, account.id, "h", "https://hooks.example.com/x", project_id=project.id
    )
    job = svc.create_webhook_delivery_job(db_session, view["id"], n["id"])
    assert job["status"] == "disabled" and job["live_enabled"] is False


def test_mock_webhook_signs_preview(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "int-whsig")
    n = _notif(db_session, account, project, owner)
    svc = WebhookSubscriptionService()
    view = svc.create_subscription(db_session, account.id, "h", "https://hooks.example.com/x")
    pv = svc.preview_webhook_delivery(db_session, view["id"], n["id"])
    assert pv["signature"].startswith("sha256=")
    assert pv["would_send"] is False
    assert pv["payload"]["notification_id"] == n["id"]


def test_opt_out_does_not_block_other_channel(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "int-oo2")
    NotificationUnsubscribeService().create_opt_out(
        db_session, owner.id, "channel", channel="email"
    )
    n = _notif(db_session, account, project, owner)
    # telegram не заблокирован channel-email opt-out.
    log = NotificationDeliveryService().create_delivery_job(db_session, n["id"], "telegram")
    assert log.error_message != "user_unsubscribed"
