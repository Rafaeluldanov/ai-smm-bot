"""Статические safety-проверки авто-синхронизации Яндекс Диска (v0.5.7, Часть 17).

Гарантии на уровне исходников: нет publish_due; API не публикует и не удаляет; нет delete-эндпоинта;
config-дефолты безопасны; сервис не удаляет/не скрывает файлы.
"""

import importlib
import inspect

from app.config import Settings

_SYNC_MODULES = (
    "app.services.yandex_auto_sync_service",
    "app.repositories.yandex_auto_sync_repository",
    "app.api.yandex_auto_sync",
    "app.scripts.yandex_sync_profile",
    "app.scripts.yandex_sync_preview",
    "app.scripts.yandex_sync_run",
    "app.scripts.yandex_sync_worker_tick",
)


def _source(module_name: str) -> str:
    return inspect.getsource(importlib.import_module(module_name))


def test_no_publish_due() -> None:
    for module in _SYNC_MODULES:
        src = _source(module)
        for token in ("scripts.publish_due", "publish_due(", "publish-due", "import publish_due"):
            assert token not in src, f"{token} в {module}"


def test_api_no_live_publish() -> None:
    src = _source("app.api.yandex_auto_sync").lower()
    for token in ("publish_due", "wall.post", "sendmessage", "vk_live", "telegram_live"):
        assert token not in src


def test_no_delete_endpoint() -> None:
    src = _source("app.api.yandex_auto_sync")
    # Нет DELETE-роутов и удаления файлов.
    assert "router.delete" not in src
    assert ".delete_" not in src.lower() or "delete_webhook" not in src.lower()


def test_service_no_delete_or_hide() -> None:
    src = _source("app.services.yandex_auto_sync_service").lower()
    # Сервис не удаляет и не скрывает файлы/медиа.
    assert "delete_media" not in src
    assert "remove_file" not in src
    assert "hide_media" not in src


def test_no_live_flag_mutation() -> None:
    src = _source("app.services.yandex_auto_sync_service")
    for token in (
        "telegram_live_publishing_enabled =",
        "vk_live_publishing_enabled =",
        "instagram_live_publishing_enabled =",
        "payments_live_enabled =",
    ):
        assert token not in src


def test_config_defaults_safe() -> None:
    s = Settings()
    assert s.yandex_auto_sync_worker_enabled is False
    assert s.yandex_auto_sync_dry_run is True
    assert s.yandex_auto_sync_network_enabled is False
    assert s.yandex_auto_sync_auto_delete is False
    assert s.yandex_auto_sync_auto_hide is False
    assert s.payments_live_enabled is False
