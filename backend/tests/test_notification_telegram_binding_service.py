"""Тесты сервиса привязок Telegram (v0.5.4). Offline; chat_id encrypted/masked; токен hash."""

import pytest
from sqlalchemy.orm import Session

from app.repositories import account_repository, user_repository
from app.repositories import notification_telegram_repository as telegram_repo
from app.services.notification_telegram_binding_service import (
    NotificationTelegramBindingService,
    TelegramBindingError,
)


def _seed(db: Session, slug: str = "tbs"):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    db.commit()
    return account, owner


def _svc() -> NotificationTelegramBindingService:
    return NotificationTelegramBindingService()


def test_create_token_stores_hash_not_raw(db_session: Session) -> None:
    account, owner = _seed(db_session)
    res = _svc().create_binding_token(db_session, owner.id, account_id=account.id)
    token = res["verification_token"]
    binding = telegram_repo.get_binding_by_id(db_session, res["binding_id"])
    assert binding.status == "pending_verification"
    # В БД — только hash + prefix, не сырой токен.
    assert binding.verification_token_hash and binding.verification_token_hash != token
    assert binding.verification_token_prefix == token[:8]
    assert token not in str(binding.verification_token_hash)


def test_verify_token_stores_encrypted_masked_chat_id(db_session: Session) -> None:
    account, owner = _seed(db_session, "tbs-v")
    res = _svc().create_binding_token(db_session, owner.id, account_id=account.id)
    view = _svc().verify_binding_token(
        db_session,
        res["verification_token"],
        chat_id="123456789",
        telegram_user_id="555",
        username="ivan",
    )
    assert view["verified"] is True
    assert "***" in view["chat_id_masked"]
    binding = telegram_repo.get_binding_by_id(db_session, res["binding_id"])
    # chat_id хранится зашифрованно (не равен сырому) и есть hash.
    assert binding.chat_id_encrypted and "123456789" not in binding.chat_id_encrypted
    assert binding.chat_id_hash
    # Внутренний путь расшифровывает верно.
    assert _svc().get_delivery_destination(db_session, owner.id) == "123456789"


def test_invalid_token_rejected(db_session: Session) -> None:
    _seed(db_session, "tbs-bad")
    with pytest.raises(TelegramBindingError):
        _svc().verify_binding_token(db_session, "no-such-token", "999")


def test_verify_from_update_payload(db_session: Session) -> None:
    account, owner = _seed(db_session, "tbs-upd")
    res = _svc().create_binding_token(db_session, owner.id, account_id=account.id)
    payload = {
        "message": {
            "text": f"/start {res['verification_token']}",
            "chat": {"id": 777888},
            "from": {"id": 42, "username": "bob"},
        }
    }
    view = _svc().verify_binding_from_update(db_session, payload)
    assert view["verified"] is True
    assert "***" in view["chat_id_masked"]


def test_disable_and_revoke(db_session: Session) -> None:
    account, owner = _seed(db_session, "tbs-dr")
    res = _svc().create_binding_token(db_session, owner.id, account_id=account.id)
    _svc().verify_binding_token(db_session, res["verification_token"], chat_id="123123123")
    disabled = _svc().disable_binding(db_session, res["binding_id"], current_user_id=owner.id)
    assert disabled["status"] == "disabled"
    revoked = _svc().revoke_binding(db_session, res["binding_id"], current_user_id=owner.id)
    assert revoked["status"] == "revoked"
    binding = telegram_repo.get_binding_by_id(db_session, res["binding_id"])
    # После отзыва зашифрованный chat_id обнулён.
    assert binding.chat_id_encrypted is None


def test_public_view_no_raw_chat_id_or_token(db_session: Session) -> None:
    account, owner = _seed(db_session, "tbs-pub")
    res = _svc().create_binding_token(db_session, owner.id, account_id=account.id)
    token = res["verification_token"]
    view = _svc().verify_binding_token(db_session, token, chat_id="123456789")
    blob = str(view)
    assert "123456789" not in blob
    assert token not in blob
    assert "chat_id_encrypted" not in view
    assert "verification_token_hash" not in view


def test_foreign_user_cannot_manage(db_session: Session) -> None:
    account, owner = _seed(db_session, "tbs-own")
    other = user_repository.create_user(db_session, email="o@e.com", password_hash="x")
    db_session.commit()
    res = _svc().create_binding_token(db_session, owner.id, account_id=account.id)
    with pytest.raises(TelegramBindingError):
        _svc().disable_binding(db_session, res["binding_id"], current_user_id=other.id)
