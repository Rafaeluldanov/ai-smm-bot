"""Статические safety-проверки live-readiness (v0.5.9, Часть 18).

Гарантии на уровне исходников: сервис/API не мутируют глобальные live-флаги и не публикуют;
schedule automation по-прежнему требует глобальные флаги; UI без publish-due; config-дефолты
безопасны.
"""

import importlib
import inspect

from app.config import Settings

_MODULES = (
    "app.services.live_readiness_service",
    "app.repositories.live_readiness_repository",
    "app.api.live_readiness",
    "app.scripts.live_readiness_check",
    "app.scripts.live_readiness_platform_check",
    "app.scripts.live_readiness_enable",
    "app.scripts.live_readiness_effective_gate",
)


def _source(module_name: str) -> str:
    return inspect.getsource(importlib.import_module(module_name))


def test_no_publish_due() -> None:
    for module in _MODULES:
        src = _source(module)
        for token in ("scripts.publish_due", "publish_due(", "publish-due", "import publish_due"):
            assert token not in src, f"{token} в {module}"


def test_service_does_not_mutate_global_live_flags() -> None:
    src = _source("app.services.live_readiness_service")
    for token in (
        "telegram_live_publishing_enabled =",
        "vk_live_publishing_enabled =",
        "instagram_live_publishing_enabled =",
        "payments_live_enabled =",
        ".telegram_live_publishing_enabled=",
    ):
        assert token not in src, token


def test_api_does_not_mutate_global_live_flags() -> None:
    src = _source("app.api.live_readiness")
    for token in ("live_publishing_enabled =", "payments_live_enabled ="):
        assert token not in src


def test_api_no_live_publish_calls() -> None:
    src = _source("app.api.live_readiness").lower()
    for token in ("publish_due", "publish_post(", "wall.post", "sendmessage"):
        assert token not in src


def test_enable_methods_do_not_touch_settings_flags() -> None:
    src = _source("app.services.live_readiness_service")
    # Методы включения не должны присваивать глобальным флагам True.
    for token in ("_live_publishing_enabled = True", "payments_live_enabled = True"):
        assert token not in src


def test_schedule_automation_still_requires_global_flags() -> None:
    # would_send (реестр) остаётся первым гейтом; live-readiness фильтр только ДОБАВЛЯЕТ условие.
    src = _source("app.services.schedule_automation_service")
    assert "would_send" in src
    assert "_filter_by_live_readiness" in src
    # Фильтр не должен включать глобальные флаги.
    assert "live_publishing_enabled = True" not in src


def test_config_defaults_safe() -> None:
    s = Settings()
    assert s.live_readiness_dry_run is True
    assert s.live_readiness_auto_enable is False
    assert s.live_readiness_probe_external_api is False
    assert s.live_readiness_allow_global_flag_override is False
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.instagram_live_publishing_enabled is False
    assert s.payments_live_enabled is False
