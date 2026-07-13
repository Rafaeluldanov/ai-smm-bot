"""Тесты сервиса rate-limit доставки уведомлений — v0.5.2. Offline."""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.notification_rate_limit_service import NotificationRateLimitService


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project, owner


def _svc(**kw: object) -> NotificationRateLimitService:
    return NotificationRateLimitService(settings=Settings(**kw))


def test_below_limit_allowed(db_session: Session) -> None:
    _a, _p, owner = _seed(db_session, "rl-below")
    svc = _svc(notification_rate_limit_email_per_hour=5)
    r = svc.check_delivery_allowed(db_session, owner.id, "email")
    assert r["allowed"] is True and r["remaining"] == 5


def test_over_limit_blocked(db_session: Session) -> None:
    _a, _p, owner = _seed(db_session, "rl-over")
    svc = _svc(notification_rate_limit_email_per_hour=3)
    for _ in range(3):
        svc.record_delivery_attempt(db_session, owner.id, "email")
    r = svc.check_delivery_allowed(db_session, owner.id, "email")
    assert r["allowed"] is False and r["remaining"] == 0


def test_per_channel_limits(db_session: Session) -> None:
    _a, _p, owner = _seed(db_session, "rl-chan")
    svc = _svc(
        notification_rate_limit_email_per_hour=1, notification_rate_limit_telegram_per_hour=5
    )
    svc.record_delivery_attempt(db_session, owner.id, "email")
    assert svc.check_delivery_allowed(db_session, owner.id, "email")["allowed"] is False
    # Telegram-лимит независим.
    assert svc.check_delivery_allowed(db_session, owner.id, "telegram")["allowed"] is True


def test_no_cross_user_mixing(db_session: Session) -> None:
    _a, _p, owner = _seed(db_session, "rl-u1")
    _a2, _p2, other = _seed(db_session, "rl-u2")
    svc = _svc(notification_rate_limit_email_per_hour=1)
    svc.record_delivery_attempt(db_session, owner.id, "email")
    assert svc.check_delivery_allowed(db_session, owner.id, "email")["allowed"] is False
    # Другой пользователь не затронут.
    assert svc.check_delivery_allowed(db_session, other.id, "email")["allowed"] is True


def test_reset_window(db_session: Session) -> None:
    from app.repositories import notification_safety_repository as safety_repo

    _a, _p, owner = _seed(db_session, "rl-reset")
    svc = _svc(notification_rate_limit_email_per_hour=1)
    svc.record_delivery_attempt(db_session, owner.id, "email")
    assert svc.check_delivery_allowed(db_session, owner.id, "email")["allowed"] is False
    # Сброс бакета вручную → снова allowed.
    key = svc.build_bucket_key(owner.id, "email")
    bucket = safety_repo.get_or_create_bucket(
        db_session, key, 3600, 1, user_id=owner.id, channel="email"
    )
    safety_repo.reset_bucket(db_session, bucket)
    assert svc.check_delivery_allowed(db_session, owner.id, "email")["allowed"] is True


def test_disabled_allows_all(db_session: Session) -> None:
    _a, _p, owner = _seed(db_session, "rl-off")
    svc = _svc(notification_rate_limit_enabled=False, notification_rate_limit_email_per_hour=1)
    svc.record_delivery_attempt(db_session, owner.id, "email")
    r = svc.check_delivery_allowed(db_session, owner.id, "email")
    assert r["allowed"] is True and r["enabled"] is False


def test_dashboard(db_session: Session) -> None:
    _a, _p, owner = _seed(db_session, "rl-dash")
    svc = _svc()
    svc.record_delivery_attempt(db_session, owner.id, "email")
    dash = svc.build_rate_limit_dashboard(db_session, user_id=owner.id)
    assert dash["enabled"] is True and len(dash["buckets"]) >= 1
