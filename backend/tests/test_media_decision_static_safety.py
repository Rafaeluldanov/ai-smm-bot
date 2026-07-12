"""Статические safety-проверки автовыбора медиа (v0.4.5, Части 16–17).

Гарантируют, что новый слой автовыбора медиа НЕ тянет live-публикацию/publish_due, не светит
секреты/внутренние пути и имеет безопасные дефолты конфигурации.
"""

import inspect

from app.config import Settings

_FORBIDDEN = ("scripts.publish_due", "import publish_due", "publish_due(")


def _source(module_name: str) -> str:
    import importlib

    return inspect.getsource(importlib.import_module(module_name))


def test_service_does_not_import_publish_due() -> None:
    src = _source("app.services.schedule_media_decision_service")
    for token in _FORBIDDEN:
        assert token not in src


def test_worker_does_not_import_publish_due() -> None:
    src = _source("app.services.scheduler_worker_service")
    for token in _FORBIDDEN:
        assert token not in src


def test_automation_does_not_import_publish_due() -> None:
    src = _source("app.services.schedule_automation_service")
    for token in _FORBIDDEN:
        assert token not in src


def test_api_router_no_live_publish() -> None:
    src = _source("app.api.media_decisions")
    for token in _FORBIDDEN:
        assert token not in src
    # Роутер не выполняет живую публикацию.
    assert "live_publish" not in src or '"live": False' in src


def test_cli_scripts_no_publish_due() -> None:
    for name in (
        "app.scripts.media_decision_preview",
        "app.scripts.media_decision_create",
        "app.scripts.media_decision_dashboard",
    ):
        src = _source(name)
        for token in _FORBIDDEN:
            assert token not in src


def test_service_response_has_no_internal_path_keys() -> None:
    # Сервис нигде не ЧИТАЕТ внутренний путь к файлу медиа (комментарии не считаются).
    src = _source("app.services.schedule_media_decision_service")
    assert ".yandex_disk_path" not in src
    assert '"yandex_disk_path"' not in src
    # _decision_view — единственный публичный сериализатор строки решения; в нём нет путей/имён.
    view_src = src.split("def _decision_view", 1)[1].split("\n    def ", 1)[0]
    for token in (".yandex_disk_path", '"yandex_disk_path"', "output_path", "file_name"):
        assert token not in view_src


def test_config_defaults_safe() -> None:
    s = Settings()
    assert s.auto_media_selection_worker_enabled is False
    assert s.auto_media_selection_dry_run is True
    assert s.auto_media_selection_create_public_links is False
    # Никакие live-флаги/платежи не включаются автовыбором медиа.
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.instagram_live_publishing_enabled is False
    assert s.payments_live_enabled is False
