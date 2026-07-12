"""Тесты сервиса уведомлений (v0.5.0). Offline; без внешней доставки."""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import (
    account_repository,
    notification_repository,
    project_repository,
    user_repository,
)
from app.schemas.project import ProjectCreate
from app.services.notification_service import NotificationError, NotificationService, sanitize_text


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    other = user_repository.create_user(db, email=f"{slug}-2@e.com", password_hash="x")
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project, owner, other


def _svc(settings: Settings | None = None) -> NotificationService:
    return NotificationService(settings=settings or Settings())


def test_create_notification(db_session: Session) -> None:
    account, project, owner, _o = _seed(db_session, "ns-create")
    svc = _svc()
    view = svc.create_notification(
        db_session,
        recipient_user_id=owner.id,
        notification_type="review_assigned",
        title="Назначена задача",
        message="Проверьте задачу",
        account_id=account.id,
        project_id=project.id,
        entity_type="media_curation_task",
        entity_id=1,
    )
    assert view is not None and view["status"] == "unread"
    assert svc.unread_count(db_session, owner.id) == 1


def test_dedup_unread_notification(db_session: Session) -> None:
    account, project, owner, _o = _seed(db_session, "ns-dedup")
    svc = _svc()
    kw = {
        "notification_type": "review_comment",
        "title": "Комментарий",
        "message": "Новый комментарий",
        "account_id": account.id,
        "project_id": project.id,
        "entity_type": "media_curation_task",
        "entity_id": 7,
    }
    v1 = svc.create_notification(db_session, recipient_user_id=owner.id, **kw)
    v2 = svc.create_notification(db_session, recipient_user_id=owner.id, **kw)
    # Дедуп: второй раз не создаёт новую запись — возвращает существующую.
    assert v1["id"] == v2["id"]
    assert svc.unread_count(db_session, owner.id) == 1


def test_mark_read(db_session: Session) -> None:
    account, project, owner, _o = _seed(db_session, "ns-read")
    svc = _svc()
    v = svc.create_notification(
        db_session,
        recipient_user_id=owner.id,
        notification_type="system_notice",
        title="t",
        message="m",
        account_id=account.id,
        project_id=project.id,
    )
    out = svc.mark_read(db_session, v["id"], owner.id)
    assert out["status"] == "read"
    assert svc.unread_count(db_session, owner.id) == 0


def test_dismiss(db_session: Session) -> None:
    account, project, owner, _o = _seed(db_session, "ns-dismiss")
    svc = _svc()
    v = svc.create_notification(
        db_session,
        recipient_user_id=owner.id,
        notification_type="system_notice",
        title="t",
        message="m",
        account_id=account.id,
        project_id=project.id,
    )
    out = svc.dismiss(db_session, v["id"], owner.id)
    assert out["status"] == "dismissed"


def test_mark_all_read(db_session: Session) -> None:
    account, project, owner, _o = _seed(db_session, "ns-allread")
    svc = _svc()
    for i in range(3):
        svc.create_notification(
            db_session,
            recipient_user_id=owner.id,
            notification_type="system_notice",
            title=f"t{i}",
            message="m",
            account_id=account.id,
            project_id=project.id,
            entity_id=i,
        )
    res = svc.mark_all_read(db_session, owner.id)
    assert res["marked_read"] == 3
    assert svc.unread_count(db_session, owner.id) == 0


def test_cannot_mark_another_users_notification(db_session: Session) -> None:
    account, project, owner, other = _seed(db_session, "ns-owned")
    svc = _svc()
    v = svc.create_notification(
        db_session,
        recipient_user_id=owner.id,
        notification_type="system_notice",
        title="t",
        message="m",
        account_id=account.id,
        project_id=project.id,
    )
    try:
        svc.mark_read(db_session, v["id"], other.id)
        raise AssertionError("expected NotificationError")
    except NotificationError:
        pass


def test_metadata_sanitized(db_session: Session) -> None:
    account, project, owner, _o = _seed(db_session, "ns-sani")
    svc = _svc()
    v = svc.create_notification(
        db_session,
        recipient_user_id=owner.id,
        notification_type="system_notice",
        title="token=123456789:ABCDEFghijklmnop0123456789abcd",
        message="файл disk:/private/secret.jpg внутри",
        account_id=account.id,
        project_id=project.id,
        metadata={"api_key": "123456789:ABCDEFghijklmnop", "note": "ok"},
    )
    n = notification_repository.get_notification_by_id(db_session, v["id"])
    assert "123456789:ABCDEFghijklmnop0123456789abcd" not in n.title
    assert "disk:/private" not in n.message
    assert "api_key" not in n.notification_metadata


def test_disabled_returns_none(db_session: Session) -> None:
    account, project, owner, _o = _seed(db_session, "ns-off")
    svc = _svc(Settings(notifications_enabled=False))
    v = svc.create_notification(
        db_session,
        recipient_user_id=owner.id,
        notification_type="system_notice",
        title="t",
        message="m",
        account_id=account.id,
        project_id=project.id,
    )
    assert v is None


def test_notify_hook_never_raises(db_session: Session) -> None:
    # notify_assignee на «плохом» объекте не должен падать (hook безопасен).
    svc = _svc()

    class _Bad:
        id = 1
        # умышленно без нужных атрибутов/связей

    result = svc.notify_assignee(db_session, _Bad(), actor_user_id=None)
    assert result is None  # безопасно проглочено


def test_sanitize_text_strips_secrets() -> None:
    out = sanitize_text("token=123456789:ABCDEFghijklmnop path disk:/x/y.jpg")
    assert "123456789:ABCDEFghijklmnop" not in out
    assert "disk:/x/y.jpg" not in out
