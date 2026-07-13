"""Статические safety-проверки Telegram-подсистемы (v0.5.4, Часть 17).

Гарантии на уровне исходников: нет publish_due; HTTP-клиент (httpx) — только в
telegram_notification_provider (ленивый импорт, за всеми флагами); нет печати bot token; live/test
send выключены по умолчанию; provider отказывает по умолчанию; UI без bot token.
"""

import importlib
import inspect

from app.config import Settings
from app.services.notification_delivery import NotificationDeliveryRequest
from app.services.notification_delivery.mock_telegram_provider import MockTelegramProvider
from app.services.notification_delivery.telegram_notification_provider import (
    TelegramNotificationProvider,
)

_TELEGRAM_MODULES = (
    "app.services.telegram_notification_template_service",
    "app.services.notification_telegram_binding_service",
    "app.repositories.notification_telegram_repository",
    "app.api.notification_telegram",
    "app.scripts.telegram_binding_create",
    "app.scripts.telegram_binding_verify",
    "app.scripts.telegram_notification_preview",
    "app.scripts.telegram_test_send",
)
_PROVIDER_MODULE = "app.services.notification_delivery.telegram_notification_provider"


def _source(module_name: str) -> str:
    return inspect.getsource(importlib.import_module(module_name))


def test_telegram_modules_no_publish_due() -> None:
    for module in (*_TELEGRAM_MODULES, _PROVIDER_MODULE):
        src = _source(module)
        for token in ("scripts.publish_due", "publish_due(", "publish-due"):
            assert token not in src, f"{token} в {module}"


def test_telegram_modules_no_http_clients_except_provider() -> None:
    # httpx разрешён ТОЛЬКО в telegram_notification_provider (ленивый импорт в live-пути).
    for module in _TELEGRAM_MODULES:
        src = _source(module).lower()
        for token in ("httpx", "requests.", "urllib.request", "smtplib", "socket."):
            assert token not in src, f"{token} в {module}"


def test_provider_refuses_by_default() -> None:
    req = NotificationDeliveryRequest(
        provider="telegram_bot",
        channel="telegram",
        recipient_user_id=1,
        destination="123",
        subject="s",
        message="m",
    )
    assert TelegramNotificationProvider(Settings()).send(req).status == "disabled"
    # mock — не сеть, sandbox.
    assert MockTelegramProvider().send(req).response_metadata["sandbox"] is True


def test_no_bot_token_print() -> None:
    for module in (*_TELEGRAM_MODULES, _PROVIDER_MODULE):
        src = _source(module)
        assert "print(settings.notification_telegram_bot_token" not in src
        assert 'f"{settings.notification_telegram_bot_token' not in src
        assert "print(self._settings.notification_telegram_bot_token" not in src


def test_config_telegram_defaults_safe() -> None:
    s = Settings()
    assert s.notification_telegram_live_send_enabled is False
    assert s.notification_telegram_test_send_enabled is False
    assert s.notification_telegram_test_send_dry_run is True
    assert s.notification_telegram_live_enabled is False
    assert s.notification_external_delivery_enabled is False
    assert s.notification_telegram_live_send_enabled_effective is False


def test_provider_source_has_gate() -> None:
    src = _source(_PROVIDER_MODULE)
    assert "_blocked_reason" in src
    # httpx импортируется лениво (внутри функции), не на уровне модуля.
    assert "import httpx" in src
    assert not src.lstrip().startswith("import httpx")
