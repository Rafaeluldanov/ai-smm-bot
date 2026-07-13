"""Статические safety-проверки Calendar Assistant (v0.5.8, Часть 15).

Гарантии на уровне исходников: нет publish_due; построение/применение календаря не публикует и не
включает live-флаги; нет DELETE-эндпоинтов; config-дефолты безопасны (live-старт выключен).
"""

import importlib
import inspect

from app.config import Settings

_MODULES = (
    "app.services.autopilot_calendar_assistant_service",
    "app.repositories.autopilot_calendar_repository",
    "app.api.autopilot_calendar",
    "app.scripts.autopilot_calendar_preview",
    "app.scripts.autopilot_calendar_create",
    "app.scripts.autopilot_calendar_apply",
    "app.scripts.autopilot_calendar_dashboard",
)


def _source(module_name: str) -> str:
    return inspect.getsource(importlib.import_module(module_name))


def test_no_publish_due() -> None:
    for module in _MODULES:
        src = _source(module)
        for token in ("scripts.publish_due", "publish_due(", "publish-due", "import publish_due"):
            assert token not in src, f"{token} в {module}"


def test_api_no_live_publish() -> None:
    src = _source("app.api.autopilot_calendar").lower()
    for token in ("publish_due", "wall.post", "sendmessage", "vk_live", "telegram_live"):
        assert token not in src


def test_no_delete_endpoint() -> None:
    src = _source("app.api.autopilot_calendar")
    assert "router.delete" not in src


def test_service_no_live_flag_mutation() -> None:
    src = _source("app.services.autopilot_calendar_assistant_service")
    for token in (
        "telegram_live_publishing_enabled =",
        "vk_live_publishing_enabled =",
        "instagram_live_publishing_enabled =",
        "payments_live_enabled =",
    ):
        assert token not in src


def test_service_does_not_call_publish_due() -> None:
    src = _source("app.services.autopilot_calendar_assistant_service").lower()
    # Не вызывает публикацию (упоминание в safety-докстроке допустимо, вызовов — нет).
    for token in (
        "publish_due(",
        "scripts.publish_due",
        "import publish_due",
        "create_first_draft_now",
    ):
        assert token not in src, token


def test_config_defaults_safe() -> None:
    s = Settings()
    assert s.autopilot_calendar_live_start_enabled is False
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.instagram_live_publishing_enabled is False
    assert s.payments_live_enabled is False
