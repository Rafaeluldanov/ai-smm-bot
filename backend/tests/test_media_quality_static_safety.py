"""Статические safety-проверки оценки качества медиа (v0.4.6, Части 16–17).

Гарантируют, что слой качества медиа НЕ тянет live-публикацию/publish_due/внешний AI, не
светит секреты/внутренние пути и имеет безопасные дефолты конфигурации.
"""

import importlib
import inspect

from app.config import Settings

_FORBIDDEN = ("scripts.publish_due", "import publish_due", "publish_due(")


def _source(module_name: str) -> str:
    return inspect.getsource(importlib.import_module(module_name))


def test_service_does_not_import_publish_due() -> None:
    src = _source("app.services.media_quality_service")
    for token in _FORBIDDEN:
        assert token not in src


def test_worker_does_not_import_publish_due() -> None:
    src = _source("app.services.scheduler_worker_service")
    for token in _FORBIDDEN:
        assert token not in src


def test_api_router_no_live_publish() -> None:
    src = _source("app.api.media_quality")
    for token in _FORBIDDEN:
        assert token not in src


def test_cli_scripts_no_publish_due() -> None:
    for name in (
        "app.scripts.media_quality_preview",
        "app.scripts.media_quality_score",
        "app.scripts.media_quality_dashboard",
    ):
        src = _source(name)
        for token in _FORBIDDEN:
            assert token not in src


def test_service_no_external_ai_calls() -> None:
    # Оценка правило-ориентированная: без внешних AI/HTTP-клиентов.
    src = _source("app.services.media_quality_service")
    for token in ("openai", "anthropic", "requests.", "httpx.", "urllib.request"):
        assert token not in src.lower()


def test_snapshot_view_has_no_internal_path_keys() -> None:
    # Сервис читает yandex_disk_path лишь для флага has_yandex_path, но НЕ сериализует путь.
    # Проверяем реальное использование (ключ/атрибут), комментарии не считаются.
    src = _source("app.services.media_quality_service")
    view_src = src.split("def _snapshot_view", 1)[1].split("\n    def ", 1)[0]
    for token in (
        '"yandex_disk_path"',
        ".yandex_disk_path",
        '"file_name"',
        ".file_name",
        "output_path",
        "source_path",
    ):
        assert token not in view_src


def test_config_defaults_safe() -> None:
    s = Settings()
    assert s.media_quality_scoring_worker_enabled is False
    assert s.media_quality_scoring_dry_run is True
    assert s.media_quality_external_ai_enabled is False
    assert s.media_quality_auto_retags_enabled is False
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.instagram_live_publishing_enabled is False
    assert s.payments_live_enabled is False
