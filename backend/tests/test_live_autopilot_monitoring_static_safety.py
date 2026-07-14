"""Статические проверки безопасности мониторинга live-автопилота (v0.6.1).

Инварианты (без запуска кода):
- нигде не вызывается publish_due;
- сервис/API не включают и не меняют глобальные live-флаги;
- стоп-кран останавливается через readiness-переключатели (движок их учитывает);
- публичные представления не содержат сырых токенов/секретов;
- безопасные дефолты настроек.
"""

import importlib
import inspect

from app.config import Settings

_MODULES = (
    "app.services.live_autopilot_monitoring_service",
    "app.repositories.live_autopilot_monitoring_repository",
    "app.api.live_autopilot_monitoring",
    "app.scripts.live_autopilot_monitoring_dashboard",
    "app.scripts.live_autopilot_monitoring_health_check",
    "app.scripts.live_autopilot_monitoring_incidents",
    "app.scripts.live_autopilot_monitoring_pause",
)


def _source(module_name: str) -> str:
    return inspect.getsource(importlib.import_module(module_name))


def test_no_publish_due() -> None:
    for module in _MODULES:
        src = _source(module)
        for token in ("scripts.publish_due", "publish_due(", "import publish_due"):
            assert token not in src, f"{token} в {module}"


def test_service_does_not_mutate_global_flags() -> None:
    src = _source("app.services.live_autopilot_monitoring_service")
    for token in (
        "telegram_live_publishing_enabled =",
        "vk_live_publishing_enabled =",
        "instagram_live_publishing_enabled =",
        "payments_live_enabled =",
        "_live_publishing_enabled = True",
    ):
        assert token not in src, token


def test_api_does_not_mutate_flags_or_publish() -> None:
    src = _source("app.api.live_autopilot_monitoring").lower()
    for token in ("publish_due(", "live_publishing_enabled =", "payments_live_enabled ="):
        assert token not in src, token


def test_kill_switch_uses_readiness_switches() -> None:
    # Пауза должна выключать per-project live (движок это учитывает), а не только менять статус.
    src = _source("app.services.live_autopilot_monitoring_service")
    assert "disable_project_live" in src
    assert "disable_full_auto_live" in src
    assert "build_effective_live_gate" in src


def test_public_views_have_no_raw_token_fields() -> None:
    src = _source("app.repositories.live_autopilot_monitoring_repository")
    for token in ("api_key", "bot_token", "access_token", "secret"):
        assert token not in src.lower(), token


def test_config_defaults_safe() -> None:
    s = Settings()
    assert s.live_autopilot_monitoring_dry_run is True
    assert s.live_autopilot_monitoring_worker_enabled is False
    assert s.live_autopilot_auto_pause_enabled is False
    assert s.live_autopilot_kill_switch_require_confirmation is True
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.instagram_live_publishing_enabled is False
    assert s.payments_live_enabled is False
