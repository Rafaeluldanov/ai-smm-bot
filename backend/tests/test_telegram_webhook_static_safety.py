"""Статические safety-проверки Telegram webhook/polling (v0.5.5, Часть 17).

Гарантии на уровне исходников: нет publish_due; HTTP-клиент (httpx) — только в bot management
service (ленивый импорт, за флагами); нет печати bot token/secret; live/polling/management
выключены по умолчанию; webhook API не отправляет сообщений; update-логи без сырого chat_id/токена.
"""

import importlib
import inspect

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, user_repository
from app.repositories import notification_telegram_update_repository as update_repo
from app.services.notification_telegram_binding_service import (
    NotificationTelegramBindingService,
)
from app.services.telegram_bot_management_service import TelegramBotManagementService
from app.services.telegram_incoming_service import TelegramIncomingService

_TELEGRAM_MODULES = (
    "app.services.telegram_update_parser_service",
    "app.services.telegram_incoming_service",
    "app.repositories.notification_telegram_update_repository",
    "app.api.notification_telegram",
    "app.scripts.telegram_update_simulate",
    "app.scripts.telegram_webhook_info",
    "app.scripts.telegram_webhook_set",
    "app.scripts.telegram_polling_dry",
)
_MGMT_MODULE = "app.services.telegram_bot_management_service"


def _source(module_name: str) -> str:
    return inspect.getsource(importlib.import_module(module_name))


def test_no_publish_due() -> None:
    for module in (*_TELEGRAM_MODULES, _MGMT_MODULE):
        src = _source(module)
        for token in ("scripts.publish_due", "publish_due(", "publish-due"):
            assert token not in src, f"{token} в {module}"


def test_no_http_clients_except_management() -> None:
    # httpx разрешён ТОЛЬКО в bot management service (ленивый импорт в live-пути).
    for module in _TELEGRAM_MODULES:
        src = _source(module).lower()
        for token in ("httpx", "requests.", "urllib.request", "smtplib", "socket."):
            assert token not in src, f"{token} в {module}"


def test_management_refuses_by_default() -> None:
    m = TelegramBotManagementService(settings=Settings())
    assert m.set_webhook_live().get("status") == "disabled"
    assert m.poll_updates_live().get("status") == "disabled"


def test_management_httpx_lazy() -> None:
    src = _source(_MGMT_MODULE)
    assert "import httpx" in src
    # httpx импортируется внутри функции (лениво), не на уровне модуля.
    assert not src.lstrip().startswith("import httpx")
    for line in src.splitlines():
        if line.startswith("import httpx"):  # без отступа = модульный уровень
            raise AssertionError("httpx импортирован на уровне модуля")


def test_no_bot_token_or_secret_print() -> None:
    for module in (*_TELEGRAM_MODULES, _MGMT_MODULE):
        src = _source(module)
        assert "print(settings.notification_telegram_bot_token" not in src
        assert "print(self._settings.notification_telegram_bot_token" not in src
        assert "print(settings.notification_telegram_webhook_secret_token" not in src


def test_webhook_api_does_not_send_messages() -> None:
    src = _source("app.api.notification_telegram").lower()
    for token in ("sendmessage", "wall.post", "publish_due"):
        assert token not in src


def test_config_defaults_safe() -> None:
    s = Settings()
    assert s.notification_telegram_webhook_live_enabled is False
    assert s.notification_telegram_polling_live_enabled is False
    assert s.notification_telegram_webhook_management_live_enabled is False
    assert s.notification_telegram_polling_dry_run is True
    assert s.notification_telegram_webhook_management_dry_run is True
    assert s.notification_external_delivery_enabled is False


def test_update_logs_no_raw_chat_id_or_token(db_session: Session) -> None:
    owner = user_repository.create_user(db_session, email="ss@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="ss", slug="ss", owner_user_id=owner.id
    )
    db_session.commit()
    res = NotificationTelegramBindingService().create_binding_token(
        db_session, owner.id, account_id=account.id
    )
    token = res["verification_token"]
    inc = TelegramIncomingService(settings=Settings())
    inc.simulate_update(db_session, token, "123456789", username="ivan")
    for log in update_repo.list_recent(db_session):
        blob = f"{log.text_preview}{log.raw_update_sanitized}{log.chat_id_hash}"
        assert token not in blob
        assert "123456789" not in blob
