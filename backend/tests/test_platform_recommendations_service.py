"""Тесты PlatformRecommendationsService (v1.0.1, offline).

Инварианты: загрузка/валидация базы; нормализация slug + алиасы (в т. ч. фактические slug каталога
проекта odnoklassniki/two_gis); список платформ; рекомендации по платформе; универсальные;
неизвестная платформа → UnknownPlatformError; path traversal невозможен; кэш возвращает копии.
"""

import pytest

from app.services.platform_recommendations_service import (
    PlatformRecommendationsService,
    UnknownPlatformError,
    get_platform_recommendations_service,
)

_SVC = get_platform_recommendations_service()

_ALIAS_CASES = [
    ("odnoklassniki", "ok"),  # фактический slug каталога проекта
    ("two_gis", "2gis"),  # фактический slug каталога проекта
    ("gis2", "2gis"),
    ("zen", "dzen"),
    ("yandex_dzen", "dzen"),
    ("vkontakte", "vk"),
    ("vk_com", "vk"),
    ("site", "website"),
    ("web", "website"),
    ("email_marketing", "email"),
]


def test_factory_returns_service() -> None:
    assert isinstance(get_platform_recommendations_service(), PlatformRecommendationsService)


def test_load_knowledge_base_has_required_keys() -> None:
    kb = _SVC.load_knowledge_base()
    for key in ("version", "product", "platforms", "universal_principles", "pre_publish_checklist"):
        assert key in kb


def test_validate_knowledge_base_passes() -> None:
    assert _SVC.validate_knowledge_base() is True


def test_normalize_canonical_slugs() -> None:
    for slug in (
        "instagram",
        "telegram",
        "vk",
        "youtube",
        "rutube",
        "dzen",
        "ok",
        "website",
        "2gis",
        "email",
    ):
        assert _SVC.normalize_platform_slug(slug) == slug


@pytest.mark.parametrize("alias,canonical", _ALIAS_CASES)
def test_normalize_aliases(alias: str, canonical: str) -> None:
    assert _SVC.normalize_platform_slug(alias) == canonical


def test_normalize_unknown_raises() -> None:
    with pytest.raises(UnknownPlatformError):
        _SVC.normalize_platform_slug("facebook")


def test_list_platforms_shape() -> None:
    platforms = _SVC.list_platforms()
    assert len(platforms) == 10
    for p in platforms:
        assert set(p) == {"slug", "title", "role", "frequency_summary"}
        assert p["title"] and p["role"]


def test_get_platform_recommendations_shape() -> None:
    rec = _SVC.get_platform_recommendations("telegram")
    for key in (
        "version",
        "platform",
        "title",
        "role",
        "signals",
        "frequency",
        "content_rules",
        "formats",
        "risks",
        "kpi",
        "weekly_rhythm",
        "universal_principles",
        "pre_publish_checklist",
        "cross_platform_notes",
    ):
        assert key in rec, key
    assert rec["platform"] == "telegram"
    assert len(rec["universal_principles"]) == 8
    assert len(rec["pre_publish_checklist"]) == 8


def test_get_platform_recommendations_via_alias() -> None:
    rec = _SVC.get_platform_recommendations("odnoklassniki")
    assert rec["platform"] == "ok"
    assert rec["title"] == "Одноклассники"


def test_cross_platform_notes_for_social() -> None:
    rec = _SVC.get_platform_recommendations("telegram")
    assert rec["cross_platform_notes"]
    assert all("→" in n for n in rec["cross_platform_notes"])


def test_get_universal_recommendations() -> None:
    uni = _SVC.get_universal_recommendations()
    assert uni["product"] == "Botfleet"
    assert len(uni["universal_principles"]) == 8
    assert "cross_platform_pipeline" in uni
    assert "weekly_rhythm" in uni


def test_unknown_platform_raises() -> None:
    with pytest.raises(UnknownPlatformError):
        _SVC.get_platform_recommendations("myspace")


@pytest.mark.parametrize(
    "attack",
    [
        "../../etc/passwd",
        "..%2f..%2fpasswd",
        "/absolute/path",
        "telegram/../../secret",
        "..\\..\\x",
    ],
)
def test_path_traversal_slug_blocked(attack: str) -> None:
    with pytest.raises(UnknownPlatformError):
        _SVC.get_platform_recommendations(attack)


def test_cache_returns_independent_copies() -> None:
    """Мутация возвращённого объекта не влияет на кэш (read-only cache)."""
    a = _SVC.get_platform_recommendations("vk")
    a["kpi"].append("ПОДДЕЛКА")
    a["role"] = "изменено"
    b = _SVC.get_platform_recommendations("vk")
    assert "ПОДДЕЛКА" not in b["kpi"]
    assert b["role"] != "изменено"
