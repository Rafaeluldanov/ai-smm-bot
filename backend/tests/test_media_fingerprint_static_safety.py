"""Статические safety-проверки fingerprint/дедупликации медиа (v0.4.7, Часть 19)."""

import importlib
import inspect

from app.config import Settings

_FORBIDDEN = ("scripts.publish_due", "import publish_due", "publish_due(")


def _source(module_name: str) -> str:
    return inspect.getsource(importlib.import_module(module_name))


def test_fingerprint_service_no_publish_due() -> None:
    for token in _FORBIDDEN:
        assert token not in _source("app.services.media_fingerprint_service")


def test_similarity_service_no_publish_due() -> None:
    for token in _FORBIDDEN:
        assert token not in _source("app.services.media_similarity_service")


def test_worker_no_publish_due() -> None:
    for token in _FORBIDDEN:
        assert token not in _source("app.services.scheduler_worker_service")


def test_api_router_no_live_publish() -> None:
    for token in _FORBIDDEN:
        assert token not in _source("app.api.media_fingerprints")


def test_cli_scripts_no_publish_due() -> None:
    for name in (
        "app.scripts.media_fingerprint_preview",
        "app.scripts.media_fingerprint_calculate",
        "app.scripts.media_duplicate_preview",
        "app.scripts.media_duplicate_calculate",
        "app.scripts.media_duplicate_dashboard",
    ):
        for token in _FORBIDDEN:
            assert token not in _source(name)


def test_no_external_ai_or_network_calls() -> None:
    # Fingerprint/similarity — локально, без внешних AI/HTTP.
    for module in (
        "app.services.media_fingerprint_service",
        "app.services.media_similarity_service",
    ):
        src = _source(module).lower()
        for token in ("openai", "anthropic", "requests.", "httpx.", "urllib.request"):
            assert token not in src


def test_fingerprint_snapshot_view_no_internal_paths() -> None:
    src = _source("app.services.media_fingerprint_service")
    view_src = src.split("def snapshot_view", 1)[1].split("\n    def ", 1)[0]
    for token in (
        '"yandex_disk_path"',
        ".yandex_disk_path",
        '"file_name"',
        ".file_name",
        "output_path",
        "raw_bytes",
    ):
        assert token not in view_src
    # Публичный вид отдаёт только префикс sha256, не полный хэш файла.
    assert "file_sha256_prefix" in view_src


def test_config_defaults_safe() -> None:
    s = Settings()
    assert s.media_fingerprinting_worker_enabled is False
    assert s.media_fingerprinting_dry_run is True
    assert s.media_fingerprinting_use_yandex_download is False
    assert s.media_fingerprinting_external_ai_enabled is False
    assert s.media_duplicate_auto_delete_enabled is False
    assert s.media_duplicate_auto_hide_enabled is False
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.instagram_live_publishing_enabled is False
    assert s.payments_live_enabled is False
