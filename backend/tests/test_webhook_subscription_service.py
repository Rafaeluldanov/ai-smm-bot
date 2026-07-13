"""Тесты сервиса webhook-подписок — v0.5.2. Offline; URL/secret encrypted+masked; без отправки."""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import (
    account_repository,
    project_repository,
    user_repository,
)
from app.repositories import (
    notification_safety_repository as safety_repo,
)
from app.schemas.project import ProjectCreate
from app.services.webhook_subscription_service import (
    WebhookSubscriptionError,
    WebhookSubscriptionService,
    mask_url,
)

_URL = "https://hooks.example.com/endpoint/abc123"


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project, owner


def _svc() -> WebhookSubscriptionService:
    return WebhookSubscriptionService(settings=Settings())


def test_create_encrypts_and_masks(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "wh-create")
    view = _svc().create_subscription(
        db_session, account.id, "hook", _URL, project_id=project.id, user_id=owner.id
    )
    assert view["url_masked"] == mask_url(_URL)
    assert view["signing_secret_present"] is True
    assert "url_encrypted" not in view and "signing_secret_encrypted" not in view
    # В хранилище — зашифровано, не сырой URL.
    row = safety_repo.get_webhook_subscription_by_id(db_session, view["id"])
    assert row.url_encrypted and _URL not in row.url_encrypted
    assert row.signing_secret_encrypted


def test_invalid_url_rejected(db_session: Session) -> None:
    account, _p, _o = _seed(db_session, "wh-badurl")
    try:
        _svc().create_subscription(db_session, account.id, "hook", "not-a-url")
        raise AssertionError("expected WebhookSubscriptionError")
    except WebhookSubscriptionError:
        pass


def test_sign_payload_deterministic() -> None:
    svc = _svc()
    sig1 = svc.sign_payload(b'{"a":1}', "secret123", 1000)
    sig2 = svc.sign_payload(b'{"a":1}', "secret123", 1000)
    assert sig1 == sig2 and sig1.startswith("sha256=")
    # Разный timestamp → разная подпись.
    assert svc.sign_payload(b'{"a":1}', "secret123", 1001) != sig1


def test_preview_no_external_call(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "wh-preview")
    svc = _svc()
    view = svc.create_subscription(db_session, account.id, "hook", _URL, project_id=project.id)
    pv = svc.preview_webhook_delivery(db_session, view["id"])
    assert pv["would_send"] is False and pv["live_enabled"] is False
    assert pv["signature"].startswith("sha256=")
    assert pv["url_masked"] == mask_url(_URL)


def test_revoke(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "wh-revoke")
    svc = _svc()
    view = svc.create_subscription(db_session, account.id, "hook", _URL)
    revoked = svc.revoke_subscription(db_session, view["id"], current_user_id=owner.id)
    assert revoked["status"] == "revoked"


def test_view_no_raw_secret_or_url(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "wh-nosecret")
    svc = _svc()
    view = svc.create_subscription(
        db_session, account.id, "hook", _URL, signing_secret="mytopsecret"
    )
    # Никаких сырых значений — только masked/present/hash.
    joined = str(view)
    assert _URL not in joined
    assert "mytopsecret" not in joined
    assert view["url_hash"] and view["signing_secret_masked"]


def test_update_subscription(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "wh-update")
    svc = _svc()
    view = svc.create_subscription(db_session, account.id, "hook", _URL)
    updated = svc.update_subscription(db_session, view["id"], title="new", status="active")
    assert updated["title"] == "new" and updated["status"] == "active"


def test_create_delivery_job_disabled(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "wh-job")
    from app.services.notification_service import NotificationService

    n = NotificationService().create_notification(
        db_session,
        recipient_user_id=owner.id,
        notification_type="system_notice",
        title="t",
        message="m",
        account_id=account.id,
        project_id=project.id,
        entity_id=1,
    )
    svc = _svc()
    view = svc.create_subscription(db_session, account.id, "hook", _URL, project_id=project.id)
    job = svc.create_webhook_delivery_job(db_session, view["id"], n["id"])
    # live выключен → задача disabled.
    assert job["status"] == "disabled" and job["live_enabled"] is False
