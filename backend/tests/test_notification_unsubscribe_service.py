"""Тесты сервиса отписки (unsubscribe/opt-out) — v0.5.2. Offline; без утечки токенов."""

import time

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
from app.services.notification_unsubscribe_service import (
    NotificationUnsubscribeError,
    NotificationUnsubscribeService,
)


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project, owner


def _svc(settings: Settings | None = None) -> NotificationUnsubscribeService:
    return NotificationUnsubscribeService(settings=settings or Settings())


def test_token_issue_verify() -> None:
    svc = _svc()
    token = svc.issue_unsubscribe_token(7, "channel", channel="email")
    payload = svc.verify_unsubscribe_token(token)
    assert payload is not None
    assert payload["uid"] == 7 and payload["scope"] == "channel" and payload["ch"] == "email"


def test_expired_token_rejected() -> None:
    import json

    from app.services import notification_unsubscribe_service as mod

    svc = _svc()
    now = int(time.time())
    payload = {"uid": 7, "scope": "global", "exp": now - 10, "iat": now - 100}
    body = mod._b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    token = f"{body}.{svc._sign(body)}"  # корректная подпись, но exp в прошлом
    assert svc.verify_unsubscribe_token(token) is None


def test_tampered_token_rejected() -> None:
    svc = _svc()
    token = svc.issue_unsubscribe_token(7, "global")
    body, _, _sig = token.partition(".")
    tampered = f"{body}.deadbeef"
    assert svc.verify_unsubscribe_token(tampered) is None


def test_invalid_token_safe() -> None:
    svc = _svc()
    assert svc.verify_unsubscribe_token("garbage") is None
    assert svc.verify_unsubscribe_token("") is None
    assert svc.verify_unsubscribe_token("a.b.c.d") is None


def test_create_opt_out_from_token(db_session: Session) -> None:
    _a, _p, owner = _seed(db_session, "unsub-tok")
    svc = _svc()
    token = svc.issue_unsubscribe_token(owner.id, "channel", channel="email")
    result = svc.create_opt_out_from_token(db_session, token)
    assert result["scope"] == "channel" and result["channel"] == "email"
    assert safety_repo.is_opted_out(db_session, owner.id, channel="email") is not None


def test_create_opt_out_direct_and_revoke(db_session: Session) -> None:
    _a, _p, owner = _seed(db_session, "unsub-dir")
    svc = _svc()
    result = svc.create_opt_out(db_session, owner.id, "global", current_user_id=owner.id)
    assert result["scope"] == "global"
    # global блокирует любой канал.
    assert safety_repo.is_opted_out(db_session, owner.id, channel="telegram") is not None
    revoked = svc.revoke_opt_out(db_session, result["id"], current_user_id=owner.id)
    assert revoked["status"] == "revoked"
    assert safety_repo.is_opted_out(db_session, owner.id, channel="telegram") is None


def test_revoke_requires_owner(db_session: Session) -> None:
    _a, _p, owner = _seed(db_session, "unsub-own")
    _a2, _p2, other = _seed(db_session, "unsub-own2")
    svc = _svc()
    result = svc.create_opt_out(db_session, owner.id, "global")
    try:
        svc.revoke_opt_out(db_session, result["id"], current_user_id=other.id)
        raise AssertionError("expected NotificationUnsubscribeError")
    except NotificationUnsubscribeError:
        pass


def test_bad_token_from_token_raises(db_session: Session) -> None:
    svc = _svc()
    try:
        svc.create_opt_out_from_token(db_session, "invalid")
        raise AssertionError("expected error")
    except NotificationUnsubscribeError:
        pass


def test_no_secret_in_token_payload() -> None:
    svc = _svc()
    token = svc.issue_unsubscribe_token(7, "global")
    # Токен не содержит сырого секрета подписи.
    secret = Settings().notification_unsubscribe_token_secret_effective
    assert secret not in token
    assert time.time  # sanity
