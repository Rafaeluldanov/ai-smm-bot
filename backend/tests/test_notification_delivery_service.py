"""Тесты сервиса доставки уведомлений (v0.5.1). Offline; без сети; sandbox."""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import (
    account_repository,
    project_repository,
    user_repository,
)
from app.repositories import (
    notification_delivery_repository as delivery_repo,
)
from app.schemas.project import ProjectCreate
from app.services.notification_delivery import (
    NotificationDeliveryRequest,
    NotificationDeliveryResult,
)
from app.services.notification_delivery_service import (
    NotificationDeliveryError,
    NotificationDeliveryService,
)
from app.services.notification_service import NotificationService

_SECRET = "123456789:secretTELEGRAMtoken0123456789abcd"


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project, owner


def _notification(db: Session, account, project, owner, **kw):  # noqa: ANN001, ANN003, ANN202
    return NotificationService().create_notification(
        db,
        recipient_user_id=owner.id,
        notification_type=kw.get("notification_type", "review_assigned"),
        title=kw.get("title", "Заголовок"),
        message=kw.get("message", "Сообщение"),
        account_id=account.id,
        project_id=project.id,
        entity_id=kw.get("entity_id", 1),
    )


def _svc(settings: Settings | None = None, providers=None) -> NotificationDeliveryService:  # noqa: ANN001
    return NotificationDeliveryService(providers=providers, settings=settings or Settings())


class _FailingProvider:
    provider_name = "mock"
    channel = "email"

    def send(self, request: NotificationDeliveryRequest) -> NotificationDeliveryResult:
        return NotificationDeliveryResult(
            ok=False,
            status="failed",
            provider="mock",
            channel=request.channel,
            destination_masked="x***@e.com",
            error_message="boom",
            response_metadata={},
        )


class _FailingRegistry:
    def resolve(self, channel: str):  # noqa: ANN001, ANN201
        return _FailingProvider()


def test_create_delivery_job(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "dlv-create")
    n = _notification(db_session, account, project, owner)
    log = _svc().create_delivery_job(db_session, n["id"], "email")
    assert log.id >= 1
    assert log.status == "pending"
    assert log.provider == "mock"
    assert "@" in (log.destination_masked or "")


def test_mock_email_sends_without_network(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "dlv-send")
    n = _notification(db_session, account, project, owner)
    svc = _svc()
    log = svc.create_delivery_job(db_session, n["id"], "email")
    result = svc.send_delivery(db_session, log.id, dry_run=False)
    assert result["outcome"] == "sent"
    assert result["provider"] == "mock"
    fresh = delivery_repo.get_delivery_log_by_id(db_session, log.id)
    assert fresh.status == "sent"
    assert fresh.provider_message_id and fresh.provider_message_id.startswith("mock-")


def test_dry_run_skips(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "dlv-dry")
    n = _notification(db_session, account, project, owner)
    svc = _svc()
    log = svc.create_delivery_job(db_session, n["id"], "email")
    result = svc.send_delivery(db_session, log.id, dry_run=True)
    assert result["outcome"] == "skipped"


def test_external_disabled_prevents_live_provider(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "dlv-ext")
    n = _notification(db_session, account, project, owner)
    # Даже если включить email+live, но external off → провайдер остаётся mock.
    s = Settings(notification_email_enabled=True, notification_email_live_enabled=True)
    svc = _svc(s)
    log = svc.create_delivery_job(db_session, n["id"], "email")
    result = svc.send_delivery(db_session, log.id, dry_run=False)
    assert result["provider"] == "mock"
    assert result["outcome"] == "sent"


def test_retry_schedules_backoff(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "dlv-retry")
    n = _notification(db_session, account, project, owner)
    svc = _svc(Settings(notification_delivery_max_attempts=3), providers=_FailingRegistry())
    log = svc.create_delivery_job(db_session, n["id"], "email")
    r1 = svc.send_delivery(db_session, log.id, dry_run=False)
    assert r1["outcome"] == "retry_scheduled"
    fresh = delivery_repo.get_delivery_log_by_id(db_session, log.id)
    assert fresh.attempts == 1 and fresh.next_retry_at is not None
    r2 = svc.send_delivery(db_session, log.id, dry_run=False)
    assert r2["outcome"] == "retry_scheduled"
    r3 = svc.send_delivery(db_session, log.id, dry_run=False)
    assert r3["outcome"] == "failed"


def test_destination_masked(db_session: Session) -> None:
    svc = _svc()
    assert svc.mask_destination("email", "stanislav@example.ru") == "s***@example.ru"
    assert "***" in svc.mask_destination("telegram", "123456789")
    assert (
        svc.mask_destination("webhook", "https://hooks.example.com/x/secret") == "hooks.example.com"
    )


def test_preview_no_secrets(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "dlv-nosec")
    n = _notification(
        db_session, account, project, owner, message=f"secret {_SECRET} disk:/private/x.jpg"
    )
    pv = _svc().preview_delivery(db_session, n["id"], "email")
    assert _SECRET not in pv["message_preview"]
    assert "disk:/private" not in pv["message_preview"]
    assert pv["will_send_externally"] is False


def test_send_notification_dry_run(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "dlv-multi")
    n = _notification(db_session, account, project, owner)
    result = _svc().send_notification(
        db_session, n["id"], channels=["email", "telegram"], dry_run=True
    )
    assert result["dry_run"] is True
    assert {r["channel"] for r in result["results"]} == {"email", "telegram"}


def test_ownership_enforced(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "dlv-own")
    _a2, _p2, other = _seed(db_session, "dlv-own2")
    n = _notification(db_session, account, project, owner)
    try:
        _svc().preview_delivery(db_session, n["id"], "email", current_user_id=other.id)
        raise AssertionError("expected NotificationDeliveryError")
    except NotificationDeliveryError:
        pass


def test_dashboard_counts(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "dlv-dash")
    n = _notification(db_session, account, project, owner)
    svc = _svc()
    log = svc.create_delivery_job(db_session, n["id"], "email")
    svc.send_delivery(db_session, log.id, dry_run=False)
    dash = svc.build_delivery_dashboard(db_session, project_id=project.id)
    assert dash["sent"] >= 1
    assert dash["external_delivery_enabled"] is False
