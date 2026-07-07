"""Тесты SEO-заполнения VK-группы (превью и гейты apply)."""

import httpx
import pytest

from app.config import Settings
from app.services.vk_group_seo_setup_service import (
    VkGroupSetupLiveDisabledError,
    VkGroupSetupProjectNotAllowedError,
    apply_vk_group_setup,
    build_vk_group_description,
    build_vk_group_status,
    build_vk_seo_hashtags,
    preview_vk_group_setup,
)


def _settings(*, live: bool, allowed: str = "teeon,fabric-souvenirs") -> Settings:
    return Settings(
        vk_group_setup_live_enabled=live,
        vk_group_setup_allowed_projects=allowed,
    )


def test_preview_makes_no_real_vk_api_call(monkeypatch: pytest.MonkeyPatch) -> None:
    # Любая попытка сетевого вызова должна упасть — превью её не делает.
    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("Сетевой вызов запрещён в preview")

    monkeypatch.setattr(httpx, "Client", _boom)
    preview = preview_vk_group_setup("teeon")
    assert preview.group_name.startswith("TEEON")
    assert preview.services
    assert preview.menu


def test_teeon_hashtags_exact() -> None:
    hashtags = build_vk_seo_hashtags("teeon")
    assert len(hashtags) == 17
    assert hashtags[0] == "#мерч"
    assert "#DTFпечать" in hashtags
    assert "#TEEON" in hashtags


def test_full_description_contains_required_blocks() -> None:
    text = build_vk_group_description("teeon")
    assert "DTF" in text
    assert "УФ-печать" in text
    assert "B2B" in text
    assert "Доставка по России" in text
    assert "+7 (495) 152-37-45" in text
    assert "teeon@upgifts.ru" in text
    assert "https://teeon.ru" in text


def test_status_line() -> None:
    assert build_vk_group_status("teeon") == (
        "Корпоративный мерч и промо-одежда на заказ | Пошив и нанесение логотипа"
    )


def test_apply_dry_run_makes_no_changes() -> None:
    result = apply_vk_group_setup("teeon", dry_run=True, settings=_settings(live=False))
    assert result.dry_run is True
    assert result.applied is False
    assert len(result.actions) == 5
    assert any("dry_run" in w.lower() for w in result.warnings)


def test_apply_live_without_flag_is_blocked() -> None:
    with pytest.raises(VkGroupSetupLiveDisabledError):
        apply_vk_group_setup("teeon", dry_run=False, settings=_settings(live=False))


def test_apply_live_with_flag_still_safe() -> None:
    # Флаг включён и проект разрешён — но реальные изменения не отправляются.
    result = apply_vk_group_setup("teeon", dry_run=False, settings=_settings(live=True))
    assert result.applied is False
    assert result.live_enabled is True
    assert any("safety" in w.lower() for w in result.warnings)


def test_apply_project_not_allowed_is_blocked() -> None:
    with pytest.raises(VkGroupSetupProjectNotAllowedError):
        apply_vk_group_setup(
            "fabric-souvenirs", dry_run=False, settings=_settings(live=True, allowed="teeon")
        )
