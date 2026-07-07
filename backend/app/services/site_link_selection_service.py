"""Выбор релевантной ссылки на сайт проекта для поста.

Подбирает ОДНУ страницу сайта (teeon.ru) под тему поста на основе темы, заголовка,
тегов медиа, продуктов, технологий и SEO-кластера. Правила (Задача 3):

- если используется НАЗВАННАЯ технология (DTF, вышивка, гравировка, …) — ведём на
  страницу технологии (``/branding/...``); у УФ-печати и термотрансфера нет
  отдельной страницы — они ведут на корневую ``/branding``;
- иначе если есть продукт — ведём на страницу продукта (``/catalog/...``);
- общая тема «мерч под ключ» / «корпоративная одежда» — на лендинг мерча;
- кейсы/портфолио — на ``/portfolio``;
- если точной страницы нет — fallback на главную.

Одна ссылка на пост (без спама). Детерминированно, без сети и БД.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from app.services.seo_content_sources import (
    ProjectSeoProfile,
    SitePage,
    UnknownSeoProjectError,
    get_project_seo_profile,
)


@dataclass(frozen=True)
class SiteLink:
    """Выбранная ссылка на страницу сайта под пост."""

    url: str
    title: str
    page_type: str
    matched_by: str  # technology | product | landing | portfolio | home
    reason: str


def _normalize(text: str) -> str:
    return text.lower().replace("ё", "е")


def _normset(values: Iterable[str]) -> set[str]:
    return {_normalize(v) for v in values if v}


def _page_by_slug(profile: ProjectSeoProfile, slug: str) -> SitePage | None:
    for page in (*profile.catalog_pages, *profile.branding_pages, *profile.other_pages):
        if page.slug == slug:
            return page
    return None


def _matches(needle: str, haystack_full: str, haystack_words: list[str]) -> bool:
    """Свободное совпадение основы слова с темой.

    Устойчиво к падежам/числу (в т. ч. беглая гласная: «футболк» ↔ «футболок»):
    односложные основы сравниваются с каждым словом по общему префиксу (5 символов)
    или вхождению; составные основы (с пробелом/дефисом) — вхождением в строку.
    """
    normalized = _normalize(needle)
    if not normalized:
        return False
    if " " in normalized or "-" in normalized:
        return normalized in haystack_full
    for word in haystack_words:
        if normalized == word:
            return True
        if len(word) < 4:  # пропускаем стоп-слова (на, с, и, по, для…)
            continue
        if len(normalized) >= 5 and len(word) >= 5 and normalized[:5] == word[:5]:
            return True
        if len(normalized) >= 4 and (normalized in word or word in normalized):
            return True
    return False


def _score_page(
    page: SitePage,
    haystack_full: str,
    haystack_words: list[str],
    products: set[str],
    technologies: set[str],
) -> int:
    """Очки соответствия страницы сигналам темы (0 — не подходит)."""
    score = 0
    for keyword in page.keywords:
        if _matches(keyword, haystack_full, haystack_words):
            score += 2
    for product in page.products:
        normalized = _normalize(product)
        if normalized in products:
            score += 3
        elif _matches(normalized, haystack_full, haystack_words):
            score += 1
    for technology in page.technologies:
        normalized = _normalize(technology)
        if normalized in technologies:
            score += 3
        elif _matches(normalized, haystack_full, haystack_words):
            score += 1
    return score


def _technologies_score(
    page: SitePage,
    haystack_full: str,
    haystack_words: list[str],
    technologies: set[str],
) -> int:
    """Очки только по НАЗВАННЫМ технологиям страницы (без общих keywords)."""
    score = 0
    for technology in page.technologies:
        normalized = _normalize(technology)
        if normalized in technologies:
            score += 3
        elif _matches(normalized, haystack_full, haystack_words):
            score += 1
    return score


def _best_page(
    pages: Iterable[SitePage],
    haystack_full: str,
    haystack_words: list[str],
    products: set[str],
    technologies: set[str],
) -> tuple[SitePage, int] | None:
    """Лучшая страница из списка по скору (тай-брейк — приоритет страницы)."""
    best: tuple[SitePage, int] | None = None
    for page in pages:
        if not page.url:
            continue
        score = _score_page(page, haystack_full, haystack_words, products, technologies)
        if score <= 0:
            continue
        if best is None or (score, page.priority) > (best[1], best[0].priority):
            best = (page, score)
    return best


def select_site_link(
    project_slug: str,
    *,
    title: str = "",
    cluster: str = "",
    seo_query: str = "",
    products: Iterable[str] = (),
    technologies: Iterable[str] = (),
    tags: dict[str, object] | None = None,
) -> SiteLink | None:
    """Выбрать релевантную ссылку на сайт для поста. None — если сайта/страниц нет.

    Технология приоритетнее продукта: при названной технологии ведём на страницу
    технологии. Продукт — на страницу продукта. Общая тема — на лендинг мерча,
    кейсы — на портфолио, иначе — на главную.
    """
    try:
        profile = get_project_seo_profile(project_slug)
    except UnknownSeoProjectError:
        return None
    if not profile.site_url:
        return None

    products_set = _normset(products)
    technologies_set = _normset(technologies)
    tag_tokens: list[str] = []
    for group in ("products", "technologies", "details", "topics", "categories"):
        raw = (tags or {}).get(group, [])
        values = raw if isinstance(raw, list | tuple) else []
        for value in values:
            token = _normalize(str(value))
            tag_tokens.append(token)
            if group == "products":
                products_set.add(token)
            if group == "technologies":
                technologies_set.add(token)

    haystack_full = _normalize(
        " ".join([title, cluster, seo_query, *products_set, *technologies_set, *tag_tokens])
    )
    haystack_words = haystack_full.split()

    branding_root = _page_by_slug(profile, "branding")

    # 1. Названная технология с отдельной страницей (DTF, вышивка, гравировка, …).
    tech_best = _best_page(
        profile.branding_pages, haystack_full, haystack_words, products_set, technologies_set
    )
    if tech_best is not None:
        page = tech_best[0]
        return SiteLink(
            url=page.url,
            title=page.title,
            page_type=page.page_type,
            matched_by="technology",
            reason=f"Технология «{page.title}» → страница нанесения",
        )

    # 2. Названная технология без отдельной страницы (УФ-печать, термотрансфер) →
    #    корневая /branding. Сопоставляем ТОЛЬКО по названиям технологий страницы,
    #    а не по общим словам «нанесение»/«брендирование» (иначе продуктовые темы
    #    ошибочно уводит на /branding вместо страницы изделия).
    if branding_root is not None and branding_root.url:
        named_score = _technologies_score(
            branding_root, haystack_full, haystack_words, technologies_set
        )
        if named_score > 0:
            return SiteLink(
                url=branding_root.url,
                title=branding_root.title,
                page_type=branding_root.page_type,
                matched_by="technology",
                reason="Технология без отдельной страницы → раздел нанесений",
            )

    # 3. Продукт → страница каталога (или лендинг мерча).
    landing = _page_by_slug(profile, "korporativnyy-merch")
    product_candidates: list[SitePage] = list(profile.catalog_pages)
    if landing is not None:
        product_candidates.append(landing)

    product_best = _best_page(
        product_candidates, haystack_full, haystack_words, products_set, technologies_set
    )
    if product_best is not None:
        page = product_best[0]
        matched = "landing" if page.slug == "korporativnyy-merch" else "product"
        return SiteLink(
            url=page.url,
            title=page.title,
            page_type=page.page_type,
            matched_by=matched,
            reason=f"Продукт/направление «{page.title}» → релевантная страница",
        )

    # 4. Общая тема нанесения (без продукта и без названной технологии) → /branding.
    if branding_root is not None and branding_root.url:
        generic_score = sum(
            2
            for keyword in branding_root.keywords
            if _matches(keyword, haystack_full, haystack_words)
        )
        if generic_score > 0:
            return SiteLink(
                url=branding_root.url,
                title=branding_root.title,
                page_type=branding_root.page_type,
                matched_by="branding",
                reason="Общая тема нанесения логотипа → раздел нанесений",
            )

    # 5. Общие темы: портфолио/кейсы → /portfolio, иначе — лендинг мерча/главная.
    if any(word in haystack_full for word in ("портфолио", "кейс", "пример", "работы")):
        portfolio = _page_by_slug(profile, "portfolio")
        if portfolio is not None and portfolio.url:
            return SiteLink(
                url=portfolio.url,
                title=portfolio.title,
                page_type=portfolio.page_type,
                matched_by="portfolio",
                reason="Тема кейса/портфолио → раздел работ",
            )
    if landing is not None and landing.url:
        return SiteLink(
            url=landing.url,
            title=landing.title,
            page_type=landing.page_type,
            matched_by="landing",
            reason="Общая тема мерча → лендинг «мерч под ключ»",
        )

    home = _page_by_slug(profile, "home") or (
        profile.other_pages[0] if profile.other_pages else None
    )
    url = home.url if home is not None else profile.site_url
    return SiteLink(
        url=url or profile.site_url,
        title=home.title if home is not None else profile.brand_name,
        page_type="home",
        matched_by="home",
        reason="Точной страницы нет → главная сайта",
    )
