"""Тесты выбора релевантной ссылки на сайт для поста."""

from app.services.site_link_selection_service import select_site_link


def test_futbolki_query_selects_catalog_futbolki() -> None:
    link = select_site_link("teeon", seo_query="пошив футболок с логотипом на заказ")
    assert link is not None
    assert link.url == "https://teeon.ru/catalog/futbolki"
    assert link.matched_by == "product"


def test_dtf_selects_branding_dtf() -> None:
    link = select_site_link("teeon", seo_query="DTF")
    assert link is not None
    assert link.url == "https://teeon.ru/branding/dtf-pechat"
    assert link.matched_by == "technology"


def test_gravirovka_selects_branding_gravirovka() -> None:
    link = select_site_link("teeon", technologies=["гравировка"])
    assert link is not None
    assert link.url == "https://teeon.ru/branding/gravirovka"


def test_uf_pechat_falls_back_to_branding_root() -> None:
    # У УФ-печати нет отдельной страницы — ведём на корневую /branding.
    link = select_site_link("teeon", technologies=["УФ-печать"])
    assert link is not None
    assert link.url == "https://teeon.ru/branding"


def test_generic_branding_with_product_selects_product_page() -> None:
    # Общие «нанесение»/«брендирование» без НАЗВАННОЙ технологии не должны уводить
    # продуктовую тему на /branding — ведём на страницу изделия.
    for query in (
        "пошив и брендирование футболок",
        "свитшоты под нанесение оптом",
        "толстовки оптом с нанесением",
    ):
        link = select_site_link("teeon", seo_query=query)
        assert link is not None
        assert link.matched_by == "product"
        assert "/catalog/" in link.url


def test_pure_branding_theme_selects_branding_root() -> None:
    link = select_site_link("teeon", seo_query="нанесение логотипа на изделия")
    assert link is not None
    assert link.url == "https://teeon.ru/branding"


def test_general_merch_theme_selects_landing() -> None:
    link = select_site_link("teeon", cluster="мерч под ключ", seo_query="мерч под ключ")
    assert link is not None
    assert link.url == "https://teeon.ru/korporativnyy-merch"


def test_portfolio_theme_selects_portfolio() -> None:
    link = select_site_link("teeon", seo_query="портфолио кейсы компаний")
    assert link is not None
    assert link.url == "https://teeon.ru/portfolio"


def test_media_tags_influence_choice() -> None:
    link = select_site_link(
        "teeon",
        title="Новый тираж",
        tags={"products": ["худи"], "technologies": ["вышивка"]},
    )
    # Технология приоритетнее продукта.
    assert link is not None
    assert link.url == "https://teeon.ru/branding/vyshivka"


def test_unknown_project_returns_none() -> None:
    assert select_site_link("no-such", seo_query="футболки") is None


def test_fabric_without_site_returns_none() -> None:
    # У плейсхолдера сувенирки сайт не задан — ссылки нет.
    assert select_site_link("fabric-souvenirs", seo_query="кружки") is None
