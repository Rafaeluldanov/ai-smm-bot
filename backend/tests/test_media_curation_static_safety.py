"""Статические safety-проверки курирования медиатеки (v0.4.8, Часть 19)."""

import importlib
import inspect

from app.config import Settings

_FORBIDDEN = ("scripts.publish_due", "import publish_due", "publish_due(")
_DELETE_PATTERNS = ("os.remove", ".unlink(", "shutil.rmtree", "delete_media", "os.rmdir")


def _source(module_name: str) -> str:
    return inspect.getsource(importlib.import_module(module_name))


def test_curation_service_no_publish_due() -> None:
    for token in _FORBIDDEN:
        assert token not in _source("app.services.media_curation_service")


def test_tag_service_no_publish_due() -> None:
    for token in _FORBIDDEN:
        assert token not in _source("app.services.media_tag_suggestion_service")


def test_worker_no_publish_due() -> None:
    for token in _FORBIDDEN:
        assert token not in _source("app.services.scheduler_worker_service")


def test_api_router_no_live_publish() -> None:
    for token in _FORBIDDEN:
        assert token not in _source("app.api.media_curation")


def test_cli_scripts_no_publish_due() -> None:
    for name in (
        "app.scripts.media_curation_preview",
        "app.scripts.media_curation_generate",
        "app.scripts.media_curation_apply",
        "app.scripts.media_curation_dashboard",
    ):
        for token in _FORBIDDEN:
            assert token not in _source(name)


def test_no_file_deletion_in_curation() -> None:
    # Курирование НЕ удаляет физические файлы — только теги/видимость.
    for module in (
        "app.services.media_curation_service",
        "app.repositories.media_curation_repository",
        "app.api.media_curation",
    ):
        src = _source(module)
        for token in _DELETE_PATTERNS:
            assert token not in src


def test_no_external_ai_in_curation() -> None:
    for module in (
        "app.services.media_curation_service",
        "app.services.media_tag_suggestion_service",
    ):
        src = _source(module).lower()
        for token in ("openai", "anthropic", "requests.", "httpx.", "urllib.request"):
            assert token not in src


def test_no_delete_route_in_api() -> None:
    # В роутере курирования нет DELETE-эндпоинтов (файлы не удаляются).
    src = _source("app.api.media_curation")
    assert "@router.delete" not in src
    assert ".delete(" not in src


def test_task_view_no_internal_paths() -> None:
    src = _source("app.services.media_curation_service")
    view_src = src.split("def _task_view", 1)[1].split("\n    def ", 1)[0]
    for token in ('"yandex_disk_path"', ".yandex_disk_path", '"file_name"', ".file_name"):
        assert token not in view_src


def test_config_defaults_safe() -> None:
    s = Settings()
    assert s.media_curation_worker_enabled is False
    assert s.media_curation_dry_run is True
    assert s.media_curation_auto_apply_tags is False
    assert s.media_curation_auto_hide_duplicates is False
    assert s.media_curation_auto_delete_enabled is False
    assert s.media_curation_external_ai_enabled is False
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.instagram_live_publishing_enabled is False
    assert s.payments_live_enabled is False
