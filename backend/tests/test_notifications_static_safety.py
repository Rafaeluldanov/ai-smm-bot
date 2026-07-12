"""Статические safety-проверки уведомлений (v0.5.0, Часть 20)."""

import importlib
import inspect

from app.config import Settings

_FORBIDDEN = ("scripts.publish_due", "import publish_due", "publish_due(")
_DELETE_PATTERNS = ("os.remove", ".unlink(", "shutil.rmtree", "os.rmdir")
_NOTIFICATION_MODULES = (
    "app.services.notification_service",
    "app.services.mention_parser_service",
    "app.repositories.notification_repository",
    "app.api.notifications",
    "app.scripts.notifications_inbox",
    "app.scripts.notifications_overdue_scan",
    "app.scripts.notifications_workload",
)


def _source(module_name: str) -> str:
    return inspect.getsource(importlib.import_module(module_name))


def test_modules_no_publish_due() -> None:
    for module in _NOTIFICATION_MODULES:
        src = _source(module)
        for token in _FORBIDDEN:
            assert token not in src, f"{token} в {module}"


def test_api_no_live_publish() -> None:
    src = _source("app.api.notifications").lower()
    for token in ("publish_due", "wall.post", "vk_live", "telegram_live", "live_publish"):
        assert token not in src


def test_no_external_delivery_send() -> None:
    # В сервисе уведомлений нет реальных сетевых вызовов доставки.
    src = _source("app.services.notification_service").lower()
    for token in (
        "smtplib",
        "requests.",
        "httpx.",
        "urllib.request",
        "sendmail",
        "boto3",
        "aiosmtp",
    ):
        assert token not in src


def test_no_file_deletion() -> None:
    for module in _NOTIFICATION_MODULES:
        src = _source(module)
        for token in _DELETE_PATTERNS:
            assert token not in src, f"{token} в {module}"


def test_config_defaults_safe() -> None:
    s = Settings()
    assert s.notifications_email_enabled is False
    assert s.notifications_digest_enabled is False
    assert s.notifications_webhook_enabled is False
    assert s.notifications_external_delivery_enabled is False
    assert s.notifications_worker_enabled is False
    assert s.notifications_dry_run is True
    assert s.notifications_external_delivery_enabled_effective is False
    # Никаких live-флагов/платежей.
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.payments_live_enabled is False


def test_notification_view_no_internal_paths() -> None:
    src = _source("app.services.notification_service")
    view_src = src.split("def _view", 1)[1].split("\n    @staticmethod", 1)[0]
    for token in ("yandex_disk_path", "file_name", "password_hash", "notification_metadata"):
        assert token not in view_src


def test_billing_notification_actions_free() -> None:
    from app.services import billing_service

    for usage in (
        billing_service.USAGE_NOTIFICATION_CREATE,
        billing_service.USAGE_NOTIFICATION_OVERDUE_SCAN,
        billing_service.USAGE_NOTIFICATION_DIGEST,
    ):
        assert billing_service.ACTION_COSTS[usage] == 0
