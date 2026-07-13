"""Статические safety-проверки Telegram live rollout (v0.6.0, Часть 16).

Гарантии на уровне исходников: сервис/API не вызывают publish_due и не мутируют глобальные
live-флаги; publish_once заблокирован по умолчанию и требует allow-флаг + глобальный флаг; в
публичных представлениях нет сырого токена; config-дефолты безопасны.
"""

import importlib
import inspect

from app.config import Settings

_MODULES = (
    "app.services.telegram_live_rollout_service",
    "app.repositories.live_publish_attempt_repository",
    "app.api.telegram_live_rollout",
    "app.scripts.telegram_live_rollout_dashboard",
    "app.scripts.telegram_live_rollout_preview",
    "app.scripts.telegram_live_rollout_run_dry",
    "app.scripts.telegram_live_rollout_publish_once",
)


def _source(module_name: str) -> str:
    return inspect.getsource(importlib.import_module(module_name))


def test_no_publish_due() -> None:
    # Упоминание в safety-докстроке допустимо; вызовов/импортов publish_due быть не должно.
    for module in _MODULES:
        src = _source(module)
        for token in ("scripts.publish_due", "publish_due(", "import publish_due"):
            assert token not in src, f"{token} в {module}"


def test_service_does_not_mutate_global_live_flags() -> None:
    src = _source("app.services.telegram_live_rollout_service")
    for token in (
        "telegram_live_publishing_enabled =",
        "vk_live_publishing_enabled =",
        "instagram_live_publishing_enabled =",
        "payments_live_enabled =",
        "_live_publishing_enabled = True",
    ):
        assert token not in src, token


def test_api_does_not_mutate_flags_or_publish_due() -> None:
    src = _source("app.api.telegram_live_rollout").lower()
    for token in ("publish_due(", "live_publishing_enabled =", "payments_live_enabled ="):
        assert token not in src


def test_publish_once_requires_allow_and_global_and_confirmation() -> None:
    src = _source("app.services.telegram_live_rollout_service")
    # publish-once блокеры собираются в _publish_blockers, который читает allow_real_send и гейт.
    assert "telegram_live_rollout_allow_real_send_effective" in src
    assert "telegram_live_rollout_confirmation_text_safe" in src
    assert "build_effective_live_gate" in src


def test_public_view_has_no_raw_token_fields() -> None:
    src = _source("app.repositories.live_publish_attempt_repository")
    for token in ("api_key", "bot_token", "access_token", "secret"):
        assert token not in src.lower()


def test_config_defaults_safe() -> None:
    s = Settings()
    assert s.telegram_live_rollout_dry_run is True
    assert s.telegram_live_rollout_allow_real_send is False
    assert s.telegram_live_rollout_require_confirmation is True
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.instagram_live_publishing_enabled is False
    assert s.payments_live_enabled is False
