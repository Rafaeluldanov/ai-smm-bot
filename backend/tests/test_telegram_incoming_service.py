"""Тесты сервиса входящих Telegram-апдейтов (v0.5.5). Offline; без сети; без исходящих сообщений."""

import json

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, user_repository
from app.repositories import notification_telegram_update_repository as update_repo
from app.services.notification_telegram_binding_service import (
    NotificationTelegramBindingService,
)
from app.services.telegram_incoming_service import TelegramIncomingService


def _seed(db: Session, slug: str = "tis"):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    db.commit()
    return account, owner


def _token(db: Session, owner, account, settings: Settings) -> str:  # noqa: ANN001
    res = NotificationTelegramBindingService(settings=settings).create_binding_token(
        db, owner.id, account_id=account.id
    )
    return res["verification_token"]


def _start_update(token: str, chat_id: str = "987654321", update_id: int = 1) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "text": f"/start {token}",
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": 5, "username": "ivan"},
        },
    }


def test_handle_valid_start_verifies_binding(db_session: Session) -> None:
    account, owner = _seed(db_session)
    settings = Settings()
    token = _token(db_session, owner, account, settings)
    inc = TelegramIncomingService(settings=settings)
    result = inc.handle_webhook_update(db_session, _start_update(token))
    assert result["ok"] is True
    assert result["status"] == "verified_binding"
    assert "***" in result["chat_id_masked"]


def test_duplicate_update_id_skipped(db_session: Session) -> None:
    account, owner = _seed(db_session, "tis-dup")
    settings = Settings()
    token = _token(db_session, owner, account, settings)
    inc = TelegramIncomingService(settings=settings)
    inc.handle_webhook_update(db_session, _start_update(token, update_id=100))
    dup = inc.handle_webhook_update(
        db_session, {"update_id": 100, "message": {"text": "/help", "chat": {"id": 1}}}
    )
    assert dup["status"] == "duplicate"


def test_invalid_secret_rejected_if_required(db_session: Session) -> None:
    _seed(db_session, "tis-sec")
    settings = Settings(
        notification_telegram_webhook_secret_required=True,
        notification_telegram_webhook_secret_token="expected-secret",
    )
    inc = TelegramIncomingService(settings=settings)
    result = inc.handle_webhook_update(
        db_session,
        {"update_id": 1, "message": {"text": "/help", "chat": {"id": 1}}},
        secret_header="wrong-secret",
    )
    assert result["status"] == "invalid_secret"
    assert result["ok"] is False


def test_missing_secret_allowed_in_local_default(db_session: Session) -> None:
    _seed(db_session, "tis-loc")
    inc = TelegramIncomingService(settings=Settings())  # secret not required by default
    result = inc.handle_webhook_update(
        db_session, {"update_id": 1, "message": {"text": "/help", "chat": {"id": 1}}}
    )
    assert result["status"] == "processed"


def test_unknown_update_ignored(db_session: Session) -> None:
    _seed(db_session, "tis-unk")
    inc = TelegramIncomingService(settings=Settings())
    result = inc.handle_webhook_update(db_session, {"update_id": 3, "my_chat_member": {}})
    assert result["status"] == "ignored"


def test_bad_start_token_failed(db_session: Session) -> None:
    _seed(db_session, "tis-bad")
    inc = TelegramIncomingService(settings=Settings())
    result = inc.handle_webhook_update(
        db_session, {"update_id": 4, "message": {"text": "/start no-such-token", "chat": {"id": 2}}}
    )
    assert result["status"] == "failed"
    assert result["ok"] is False


def test_no_raw_token_or_chat_id_in_logs(db_session: Session) -> None:
    account, owner = _seed(db_session, "tis-safe")
    settings = Settings()
    token = _token(db_session, owner, account, settings)
    inc = TelegramIncomingService(settings=settings)
    inc.handle_webhook_update(db_session, _start_update(token, chat_id="123456789"))
    logs = update_repo.list_recent(db_session)
    blob = json.dumps(
        [
            {
                "view": update_repo.public_update_view(x),
                "text": x.text_preview,
                "raw": x.raw_update_sanitized,
                "hash": x.chat_id_hash,
            }
            for x in logs
        ],
        ensure_ascii=False,
        default=str,
    )
    assert token not in blob
    assert "123456789" not in blob


def test_simulate_update(db_session: Session) -> None:
    account, owner = _seed(db_session, "tis-sim")
    settings = Settings()
    token = _token(db_session, owner, account, settings)
    inc = TelegramIncomingService(settings=settings)
    result = inc.simulate_update(db_session, token, "555666777", username="bob")
    assert result["status"] == "verified_binding"


def test_public_result_no_secrets(db_session: Session) -> None:
    inc = TelegramIncomingService(settings=Settings())
    cleaned = inc.public_result(
        {
            "ok": True,
            "status": "x",
            "secret": "leak",
            "raw_token": "leak",
            "chat_id_masked": "1***2",
        }
    )
    assert "secret" not in cleaned
    assert "raw_token" not in cleaned
    assert cleaned["chat_id_masked"] == "1***2"
