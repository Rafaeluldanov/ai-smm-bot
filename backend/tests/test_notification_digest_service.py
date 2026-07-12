"""Тесты сервиса дайджестов уведомлений (v0.5.1). Offline; без реальной отправки."""

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
from app.services.notification_digest_service import (
    NotificationDigestError,
    NotificationDigestService,
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


def _notify(db: Session, account, project, owner, n: int = 3):  # noqa: ANN001, ANN202
    svc = NotificationService()
    for i in range(n):
        svc.create_notification(
            db,
            recipient_user_id=owner.id,
            notification_type="review_assigned",
            title=f"Задача {i}",
            message="msg",
            account_id=account.id,
            project_id=project.id,
            entity_id=i,
        )


def _svc(settings: Settings | None = None) -> NotificationDigestService:
    return NotificationDigestService(settings=settings or Settings())


def test_preview_no_writes(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "dg-prev")
    _notify(db_session, account, project, owner, 3)
    r = _svc().preview_digest(db_session, owner.id, frequency="daily")
    assert r["notification_count"] == 3
    assert r["subject"]
    # Ничего не записано.
    assert delivery_repo.list_digests_for_user(db_session, owner.id) == []


def test_generate_dry_run_no_writes(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "dg-dry")
    _notify(db_session, account, project, owner, 2)
    r = _svc().generate_digest(db_session, owner.id, frequency="daily", dry_run=True)
    assert r["dry_run"] is True and r["digest_id"] is None
    assert delivery_repo.list_digests_for_user(db_session, owner.id) == []


def test_generate_write_mode(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "dg-write")
    _notify(db_session, account, project, owner, 2)
    r = _svc().generate_digest(db_session, owner.id, frequency="daily", dry_run=False)
    assert r["digest_id"] is not None
    digests = delivery_repo.list_digests_for_user(db_session, owner.id)
    assert len(digests) == 1
    assert digests[0].status == "generated"


def test_digest_groups_notifications(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "dg-group")
    _notify(db_session, account, project, owner, 3)
    r = _svc().preview_digest(db_session, owner.id, frequency="daily")
    body = r["body_preview"]
    assert "проект" in body.lower() or "уведомл" in body.lower()
    assert str(project.id) in body


def test_send_digest_dry_run(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "dg-send")
    _notify(db_session, account, project, owner, 2)
    svc = _svc()
    gen = svc.generate_digest(db_session, owner.id, frequency="daily", dry_run=False)
    out = svc.send_digest(db_session, gen["digest_id"], dry_run=True)
    assert out["dry_run"] is True
    # dry-run не помечает дайджест sent.
    d = delivery_repo.get_digest_by_id(db_session, gen["digest_id"])
    assert d.status != "sent"


def test_scheduler_dry_run_disabled_by_default(db_session: Session) -> None:
    _account, _project, _owner = _seed(db_session, "dg-sched")
    r = _svc().run_digest_scheduler(db_session, frequency="daily", dry_run=True)
    assert r["enabled"] is False  # дайджесты выключены по умолчанию


def test_scheduler_finds_enabled_users(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "dg-sched2")
    _notify(db_session, account, project, owner, 1)
    # Включаем настройку дайджеста (daily) для пользователя.
    from app.repositories import notification_repository

    notification_repository.set_preference(
        db_session,
        owner.id,
        "digest",
        True,
        notification_type=None,
        account_id=account.id,
        digest_frequency="daily",
    )
    db_session.commit()
    r = _svc(Settings(notification_digest_enabled=True)).run_digest_scheduler(
        db_session, frequency="daily", dry_run=True
    )
    assert r["enabled"] is True
    assert r["users"] >= 1


def test_access_enforced(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "dg-acc")
    _a2, _p2, other = _seed(db_session, "dg-acc2")
    try:
        _svc().preview_digest(db_session, owner.id, current_user_id=other.id)
        raise AssertionError("expected NotificationDigestError")
    except NotificationDigestError:
        pass


def test_no_secrets_in_digest(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "dg-nosec")
    NotificationService().create_notification(
        db_session,
        recipient_user_id=owner.id,
        notification_type="system_notice",
        title=f"secret {_SECRET}",
        message="disk:/private/x.jpg",
        account_id=account.id,
        project_id=project.id,
        entity_id=1,
    )
    r = _svc().preview_digest(db_session, owner.id, frequency="daily")
    assert _SECRET not in r["body_preview"]
    assert "disk:/private" not in r["body_preview"]
