"""Тесты SEO-профиля проекта (источники, контакты, контент-вектор)."""

import pytest

from app.services.seo_content_sources import (
    UnknownSeoProjectError,
    get_default_publication_vector,
    get_project_seo_profile,
    list_supported_seo_projects,
)


def test_teeon_profile_has_site_and_contacts() -> None:
    profile = get_project_seo_profile("teeon")
    assert profile.site_url == "https://teeon.ru"
    assert profile.brand_name == "TEEON"
    assert profile.contacts.phone == "+7 (495) 152-37-45"
    assert profile.contacts.email == "teeon@upgifts.ru"
    assert profile.contacts.city == "Москва"
    assert profile.contacts.website == "https://teeon.ru"
    assert profile.vk_group_id == "240102732"


def test_teeon_catalog_and_branding_pages() -> None:
    profile = get_project_seo_profile("teeon")
    catalog_slugs = {page.slug for page in profile.catalog_pages}
    branding_slugs = {page.slug for page in profile.branding_pages}
    assert {"futbolki", "hudi", "svitshoty", "longslivy", "kepki"} <= catalog_slugs
    assert {"dtf-pechat", "vyshivka", "gravirovka", "shelkografiya", "birki"} <= branding_slugs
    for page in (*profile.catalog_pages, *profile.branding_pages):
        assert page.url.startswith("https://teeon.ru/")


def test_teeon_content_vector_priorities() -> None:
    vector = get_project_seo_profile("teeon").content_vector
    products = dict(vector.priority_products)
    technologies = dict(vector.priority_technologies)
    assert products["футболки"] == 100
    assert products["худи"] == 95
    assert technologies["DTF-печать"] == 100
    # УФ-печать заложена приоритетной по требованию владельца.
    assert technologies["УФ-печать"] == 90
    content_mix = dict(vector.content_mix)
    assert content_mix["товары/изделия"] == 30
    assert content_mix["технологии нанесения"] == 30
    assert "B2B" in vector.tone


def test_default_publication_vector_uses_preset() -> None:
    vector = get_default_publication_vector("teeon")
    assert vector["футболки"] == 100
    assert vector["худи"] == 95
    assert vector["DTF-печать"] == 100
    assert vector["УФ-печать"] == 90


def test_fabric_souvenirs_placeholder_profile() -> None:
    profile = get_project_seo_profile("fabric-souvenirs")
    assert profile.project_slug == "fabric-souvenirs"
    assert profile.brand_name == "Фабрика сувениров"
    assert profile.site_url == ""
    assert profile.vk_group_id is None
    assert profile.content_vector.priority_products  # каркас есть


def test_supported_projects_and_unknown() -> None:
    assert set(list_supported_seo_projects()) == {"teeon", "fabric-souvenirs"}
    with pytest.raises(UnknownSeoProjectError):
        get_project_seo_profile("no-such-project")
    with pytest.raises(UnknownSeoProjectError):
        get_default_publication_vector("no-such-project")
