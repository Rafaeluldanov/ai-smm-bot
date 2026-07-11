"""Тесты каталога платформ: состав, иконки (оригинальные, без внешних URL), уровни."""

from app.services.platform_catalog_service import (
    CATEGORIES,
    PLANNED_LEVELS,
    SUPPORT_LEVELS,
    PlatformCatalogService,
)

SVC = PlatformCatalogService()

_REQUIRED = (
    "telegram",
    "vk",
    "instagram",
    "youtube",
    "rutube",
    "dzen",
    "odnoklassniki",
    "yandex_disk",
    "website",
)


def test_catalog_contains_core_platforms() -> None:
    keys = set(SVC.keys())
    for key in _REQUIRED:
        assert key in keys, key


def test_every_platform_has_icon_svg() -> None:
    for item in SVC.items():
        assert item.icon_svg.startswith("<svg"), item.key
        assert "</svg>" in item.icon_svg


def test_no_icon_has_external_url() -> None:
    for item in SVC.items():
        low = item.icon_svg.lower()
        assert "http://" not in low, item.key
        assert "https://" not in low, item.key
        assert "<image" not in low, item.key  # без растровых картинок
        assert "xlink:href" not in low, item.key


def test_planned_platforms_have_planned_support_level() -> None:
    planned = SVC.planned_items()
    assert planned, "должны быть планируемые площадки"
    for item in planned:
        assert item.support_level in PLANNED_LEVELS
    # Несколько конкретных ожидаемых planned-площадок.
    keys = {i.key for i in planned}
    for key in ("facebook_page", "tiktok", "tenchat", "vc_ru"):
        assert key in keys, key


def test_instagram_requires_public_media_url() -> None:
    ig = SVC.get("instagram")
    assert ig is not None
    assert ig.requires_public_media_url is True


def test_support_levels_and_categories_valid() -> None:
    for item in SVC.items():
        assert item.support_level in SUPPORT_LEVELS, item.key
        assert item.category in CATEGORIES, item.key


def test_active_platforms_present() -> None:
    active = {i.key for i in SVC.active_items()}
    for key in ("telegram", "vk", "instagram"):
        assert key in active, key


def test_as_dict_hides_icon_and_adds_titles() -> None:
    data = SVC.as_dict(SVC.get("telegram"))
    assert "icon_svg" not in data
    assert data["support_title"] and data["category_title"]
    assert data["is_planned"] is False
