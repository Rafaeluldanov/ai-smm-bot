"""Интеграция Telegram в доставку уведомлений (v0.5.4). Offline; sandbox; без сети.

Проверяем: без verified-привязки доставка блокируется; с привязкой mock-отправка работает;
opt-out/rate-limit/suppression блокируют telegram; dry-run не ходит в сеть; в БД-логе нет
сырого chat_id / verification token.
"""

import json
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.notification_delivery_service import NotificationDeliveryService
from app.services.notification_service import NotificationService
from app.services.notification_telegram_binding_service import (
    NotificationTelegramBindingService,
)


def _seed(db: Session, slug: str = "tdi"):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="Проект", slug=slug))
    project.account_id = account.id
    db.commit()
    n = NotificationService().create_notification(
        db,
        recipient_user_id=owner.id,
        notification_type="review_assigned",
        title="Задача ревью",
        message="Текст уведомления",
        account_id=account.id,
        project_id=project.id,
        entity_id=1,
    )
    return account, project, owner, n["id"]


def _verify_binding(db: Session, owner, account, project, chat_id: str = "123456789") -> None:  # noqa: ANN001
    svc = NotificationTelegramBindingService(settings=Settings())
    res = svc.create_binding_token(db, owner.id, account_id=account.id, project_id=project.id)
    svc.verify_binding_token(db, res["verification_token"], chat_id=chat_id)


def _log_blob(log: Any) -> str:
    return json.dumps(
        {
            "subject": log.subject,
            "message_preview": log.message_preview,
            "error_message": log.error_message,
            "request_metadata": log.request_metadata,
            "destination_masked": log.destination_masked,
        },
        ensure_ascii=False,
        default=str,
    )


def test_blocks_without_verified_binding(db_session: Session) -> None:
    account, project, owner, nid = _seed(db_session, "tdi-nob")
    service = NotificationDeliveryService(settings=Settings())
    log = service.create_delivery_job(db_session, nid, "telegram")
    assert log.status == "disabled"
    assert log.error_message == "missing_verified_telegram_binding"


def test_verified_binding_allows_mock_send(db_session: Session) -> None:
    account, project, owner, nid = _seed(db_session, "tdi-ok")
    _verify_binding(db_session, owner, account, project)
    service = NotificationDeliveryService(settings=Settings())
    log = service.create_delivery_job(db_session, nid, "telegram")
    assert log.status == "pending"
    assert log.request_metadata.get("template_type") == "review_assigned"
    assert log.request_metadata.get("binding_id")
    out = service.send_delivery(db_session, log.id, dry_run=False)
    assert out["outcome"] == "sent"


def test_log_has_no_raw_chat_id_or_token(db_session: Session) -> None:
    account, project, owner, nid = _seed(db_session, "tdi-safe")
    _verify_binding(db_session, owner, account, project, chat_id="987654321")
    service = NotificationDeliveryService(settings=Settings())
    log = service.create_delivery_job(db_session, nid, "telegram")
    blob = _log_blob(log)
    assert "987654321" not in blob
    assert "token" not in blob.lower() or "verification" not in blob.lower()
    # Адрес — только маской.
    assert "***" in log.destination_masked


def test_opt_out_blocks_telegram(db_session: Session) -> None:
    from app.repositories import notification_safety_repository as safety_repo

    account, project, owner, nid = _seed(db_session, "tdi-opt")
    _verify_binding(db_session, owner, account, project)
    safety_repo.create_opt_out(
        db_session, user_id=owner.id, scope="channel", channel="telegram", account_id=account.id
    )
    db_session.commit()
    service = NotificationDeliveryService(settings=Settings())
    log = service.create_delivery_job(db_session, nid, "telegram")
    assert log.status == "disabled"
    assert log.error_message == "user_unsubscribed"


def test_suppression_blocks_telegram(db_session: Session) -> None:
    from app.services.notification_suppression_service import NotificationSuppressionService

    account, project, owner, nid = _seed(db_session, "tdi-sup")
    _verify_binding(db_session, owner, account, project, chat_id="123456789")
    # Порог 1 → одна ошибка активирует подавление на chat_id (адрес доставки telegram).
    NotificationSuppressionService(
        settings=Settings(notification_suppression_failure_threshold=1)
    ).record_delivery_failure(db_session, owner.id, "telegram", destination="123456789")
    log = NotificationDeliveryService(
        settings=Settings(notification_suppression_failure_threshold=1)
    ).create_delivery_job(db_session, nid, "telegram")
    assert log.status == "disabled"
    assert log.error_message == "too_many_failures"


def test_rate_limit_blocks_telegram(db_session: Session) -> None:
    from app.services.notification_rate_limit_service import NotificationRateLimitService

    account, project, owner, nid = _seed(db_session, "tdi-rl")
    _verify_binding(db_session, owner, account, project)
    s = Settings(notification_rate_limit_telegram_per_hour=1)
    NotificationRateLimitService(settings=s).record_delivery_attempt(
        db_session, owner.id, "telegram"
    )
    log = NotificationDeliveryService(settings=s).create_delivery_job(db_session, nid, "telegram")
    assert log.status == "skipped"
    assert log.error_message == "rate_limited"


def test_dry_run_no_external(db_session: Session) -> None:
    account, project, owner, nid = _seed(db_session, "tdi-dry")
    _verify_binding(db_session, owner, account, project)
    service = NotificationDeliveryService(settings=Settings())
    log = service.create_delivery_job(db_session, nid, "telegram")
    out = service.send_delivery(db_session, log.id, dry_run=True)
    assert out["outcome"] == "skipped"
