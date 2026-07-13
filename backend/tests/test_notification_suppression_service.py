"""Тесты сервиса подавления доставки (suppression) — v0.5.2. Offline; без сырых адресов."""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.notification_suppression_service import (
    NotificationSuppressionService,
    hash_destination,
)


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project, owner


def _svc(**kw: object) -> NotificationSuppressionService:
    return NotificationSuppressionService(settings=Settings(**kw))


def test_failures_create_suppression_after_threshold(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "sp-thr")
    svc = _svc(notification_suppression_failure_threshold=3)
    dest = "user@example.ru"
    for _ in range(2):
        r = svc.record_delivery_failure(
            db_session, owner.id, "email", destination=dest, account_id=account.id
        )
        assert r["suppressed"] is False
    r = svc.record_delivery_failure(
        db_session, owner.id, "email", destination=dest, account_id=account.id
    )
    assert r["suppressed"] is True


def test_suppression_blocks(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "sp-block")
    svc = _svc(notification_suppression_failure_threshold=1)
    dest = "user@example.ru"
    svc.record_delivery_failure(db_session, owner.id, "email", destination=dest)
    assert svc.is_suppressed(db_session, owner.id, "email", destination=dest) is not None


def test_success_resets_failure_count(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "sp-reset")
    svc = _svc(notification_suppression_failure_threshold=3)
    dest = "user@example.ru"
    svc.record_delivery_failure(db_session, owner.id, "email", destination=dest)
    svc.record_delivery_failure(db_session, owner.id, "email", destination=dest)
    svc.record_delivery_success(db_session, owner.id, "email", destination=dest)
    # После успеха счётчик сброшен — следующий сбой не активирует подавление сразу.
    r = svc.record_delivery_failure(db_session, owner.id, "email", destination=dest)
    assert r["suppressed"] is False


def test_clear_suppression(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "sp-clear")
    svc = _svc(notification_suppression_failure_threshold=1)
    dest = "user@example.ru"
    r = svc.record_delivery_failure(db_session, owner.id, "email", destination=dest)
    out = svc.clear_suppression(db_session, r["suppression_id"], current_user_id=owner.id)
    assert out["status"] == "cleared"
    assert svc.is_suppressed(db_session, owner.id, "email", destination=dest) is None


def test_no_raw_destination_stored(db_session: Session) -> None:
    from app.repositories import notification_safety_repository as safety_repo

    account, project, owner = _seed(db_session, "sp-nodest")
    svc = _svc(notification_suppression_failure_threshold=1)
    dest = "secret-user@example.ru"
    svc.record_delivery_failure(db_session, owner.id, "email", destination=dest)
    rows = safety_repo.list_suppressions(db_session, user_id=owner.id)
    assert rows and rows[0].destination_hash == hash_destination(dest)
    assert rows[0].destination_hash != dest  # только hash, не сырой адрес


def test_disabled_no_suppression(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "sp-off")
    svc = _svc(notification_suppression_enabled=False)
    r = svc.record_delivery_failure(db_session, owner.id, "email", destination="x@e.ru")
    assert r.get("enabled") is False


def test_dashboard(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "sp-dash")
    svc = _svc(notification_suppression_failure_threshold=1)
    svc.record_delivery_failure(
        db_session, owner.id, "email", destination="x@e.ru", project_id=project.id
    )
    dash = svc.build_suppression_dashboard(db_session, project_id=project.id)
    assert dash["active"] >= 1
