"""Статические safety-проверки collaborative review курирования (v0.4.9, Часть 16)."""

import importlib
import inspect

from app.config import Settings

_FORBIDDEN = ("scripts.publish_due", "import publish_due", "publish_due(")
_DELETE_PATTERNS = ("os.remove", ".unlink(", "shutil.rmtree", "delete_media", "os.rmdir")
_REVIEW_MODULES = (
    "app.services.media_curation_review_service",
    "app.repositories.media_curation_review_repository",
    "app.api.media_curation_review",
    "app.scripts.media_curation_review_dashboard",
    "app.scripts.media_curation_review_comment",
    "app.scripts.media_curation_review_approve",
    "app.scripts.media_curation_review_apply",
)


def _source(module_name: str) -> str:
    return inspect.getsource(importlib.import_module(module_name))


def test_review_modules_no_publish_due() -> None:
    for module in _REVIEW_MODULES:
        src = _source(module)
        for token in _FORBIDDEN:
            assert token not in src, f"{token} в {module}"


def test_review_api_no_live_publish() -> None:
    src = _source("app.api.media_curation_review").lower()
    for token in ("live_publish", "publish_due", "wall.post", "vk_live", "telegram_live"):
        assert token not in src


def test_no_file_deletion_in_review() -> None:
    for module in _REVIEW_MODULES:
        src = _source(module)
        for token in _DELETE_PATTERNS:
            assert token not in src, f"{token} в {module}"


def test_no_delete_route_in_api() -> None:
    src = _source("app.api.media_curation_review")
    assert "@router.delete" not in src
    assert ".delete(" not in src


def test_no_external_ai_in_review() -> None:
    for module in (
        "app.services.media_curation_review_service",
        "app.repositories.media_curation_review_repository",
    ):
        src = _source(module).lower()
        for token in ("openai", "anthropic", "requests.", "httpx.", "urllib.request", "vision"):
            assert token not in src


def test_comment_view_no_internal_paths() -> None:
    # _comment_view отдаёт только безопасные поля (без путей к файлам).
    src = _source("app.services.media_curation_review_service")
    view_src = src.split("def _comment_view", 1)[1].split("\n    def ", 1)[0]
    for token in ("yandex_disk_path", "file_name", "comment_metadata"):
        assert token not in view_src


def test_config_defaults_safe() -> None:
    s = Settings()
    assert s.media_curation_review_require_approval is True
    assert s.media_curation_review_auto_apply_after_approval is False
    assert s.media_curation_review_notify_enabled is False
    assert s.media_curation_review_external_ai_enabled is False
    assert s.media_curation_review_require_approval_effective is True
    # Никаких live-флагов/платежей не подразумевается.
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.instagram_live_publishing_enabled is False
    assert s.payments_live_enabled is False


def test_billing_review_actions_free() -> None:
    from app.services import billing_service

    for usage in (
        billing_service.USAGE_MEDIA_CURATION_REVIEW_COMMENT,
        billing_service.USAGE_MEDIA_CURATION_REVIEW_APPROVE,
        billing_service.USAGE_MEDIA_CURATION_REVIEW_APPLY,
    ):
        assert billing_service.ACTION_COSTS[usage] == 0
