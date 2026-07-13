"""Интеграция email-рендера в доставку уведомлений (v0.5.3). Offline; sandbox; без сети.

Проверяем: при создании delivery-задачи для email subject берётся из шаблона и в metadata
попадает тип шаблона; при mock-отправке полное письмо (subject/text/html) рендерится в ЗАПРОС,
но в БД-логе НЕТ сырого unsubscribe-токена и футера (только маска/превью уведомления).
"""

import json
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import notification_delivery_repository as delivery_repo
from app.schemas.project import ProjectCreate
from app.services.notification_delivery import (
    NotificationDeliveryRequest,
    NotificationDeliveryResult,
)
from app.services.notification_delivery_service import NotificationDeliveryService
from app.services.notification_service import NotificationService


def _seed(db: Session, slug: str = "edi"):  # noqa: ANN202
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


class _CapturingProvider:
    provider_name = "mock"
    channel = "email"

    def __init__(self) -> None:
        self.request: NotificationDeliveryRequest | None = None

    def send(self, request: NotificationDeliveryRequest) -> NotificationDeliveryResult:
        self.request = request
        return NotificationDeliveryResult(
            ok=True,
            status="sent",
            provider=self.provider_name,
            channel=self.channel,
            destination_masked="u***@e.com",
            provider_message_id="mock-1",
            response_metadata={"delivered": True},
        )


class _CapturingRegistry:
    def __init__(self, provider: _CapturingProvider) -> None:
        self._provider = provider

    def resolve(self, channel: str) -> _CapturingProvider:
        return self._provider


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


def test_create_job_email_uses_template_subject_and_metadata(db_session: Session) -> None:
    _a, _p, _o, nid = _seed(db_session, "edi-job")
    service = NotificationDeliveryService(settings=Settings())
    log = service.create_delivery_job(db_session, nid, "email")
    # Subject взят из email-шаблона (не сырой title), в metadata — тип шаблона и флаг футера.
    assert log.subject
    assert log.request_metadata.get("template_type") == "review_assigned"
    assert log.request_metadata.get("has_unsubscribe_footer") is True
    # В логе НЕТ сырого токена / URL отписки (ключ has_unsubscribe_footer — это флаг, не токен).
    blob = _log_blob(log)
    assert "token=" not in blob
    assert "/unsubscribe" not in blob


def test_send_renders_full_email_into_request_not_log(db_session: Session) -> None:
    _a, _p, _o, nid = _seed(db_session, "edi-send")
    capture = _CapturingProvider()
    service = NotificationDeliveryService(
        providers=_CapturingRegistry(capture), settings=Settings()
    )
    log = service.create_delivery_job(db_session, nid, "email")
    service.send_delivery(db_session, log.id, dry_run=False)

    # Полное письмо ушло в ЗАПРОС провайдера: текст с футером (маска) + html-альтернатива.
    assert capture.request is not None
    assert "отписаться" in (capture.request.message or "").lower()
    assert "***" in (capture.request.message or "")
    assert (capture.request.metadata or {}).get("html_body")

    # А в БД-логе сырого токена/футера нет — только превью уведомления.
    refreshed = delivery_repo.get_delivery_log_by_id(db_session, log.id)
    blob = _log_blob(refreshed)
    assert "token=" not in blob
    assert "/unsubscribe" not in blob


def test_dry_run_skips_no_request(db_session: Session) -> None:
    _a, _p, _o, nid = _seed(db_session, "edi-dry")
    capture = _CapturingProvider()
    service = NotificationDeliveryService(
        providers=_CapturingRegistry(capture), settings=Settings()
    )
    log = service.create_delivery_job(db_session, nid, "email")
    out = service.send_delivery(db_session, log.id, dry_run=True)
    assert out["outcome"] == "skipped"
    # Провайдер не вызывался в dry-run.
    assert capture.request is None
