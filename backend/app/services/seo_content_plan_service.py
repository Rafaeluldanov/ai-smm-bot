"""Генерация SEO-контент-плана проекта на N дней (Задача 9).

Детерминированно и оффлайн (без сети, AI и БД): распределяет рубрики по дням
согласно контент-миксу профиля, подбирает под каждый день тему, SEO-запрос из
seed-ядра, релевантную ссылку на сайт (teeon.ru), рекомендуемый медиа-тег и CTA.

Каждый элемент плана гарантированно содержит ссылку на сайт (для проектов с
заданным сайтом). Технологические дни используют приоритетные технологии
(DTF, вышивка, гравировка, УФ-печать и т. д.).
"""

import math
from datetime import date, timedelta

from app.schemas.seo import SeoContentPlan, SeoContentPlanItem
from app.services.seo_content_sources import (
    ProjectSeoProfile,
    SeoQuery,
    find_site_page,
    get_project_seo_profile,
    rubric_title,
)
from app.services.site_link_selection_service import SiteLink, select_site_link

_WEEKDAYS_RU: tuple[str, ...] = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")

# Метки контент-микса.
_PRODUCTS = "товары/изделия"
_TECHNOLOGIES = "технологии нанесения"
_PRODUCTION = "производство/процесс"
_CASES = "кейсы/портфолио"
_FAQ = "FAQ/обучение/как выбрать"

# Продукт (мн. ч. из запросов) -> медиа-тег (ед. ч., как в тегах MediaAsset).
_PRODUCT_MEDIA_TAG: dict[str, str] = {
    "футболки": "футболка",
    "худи": "худи",
    "толстовки": "толстовка",
    "свитшоты": "свитшот",
    "лонгсливы": "лонгслив",
    "кепки": "кепка",
    "жилетки": "жилет",
    "куртки": "куртка",
    "дождевики": "дождевик",
    "сумки": "сумка",
    "мерч": "мерч",
}

# Технология (название из профиля) -> медиа-тег.
_TECHNOLOGY_MEDIA_TAG: dict[str, str] = {
    "DTF-печать": "dtf",
    "вышивка": "вышивка",
    "гравировка": "гравировка",
    "УФ-печать": "уф-печать",
    "шелкография": "шелкография",
    "DTG-печать": "dtg",
    "термотрансфер": "термотрансфер",
    "шевроны": "шеврон",
    "бирки / лейблы": "бирка",
}

_PRODUCT_TOPIC_TEMPLATES: tuple[str, ...] = (
    "{p} с логотипом на заказ",
    "{p} под корпоративный заказ",
    "{p}: расчёт тиража и сроки",
)
_TECH_TOPIC_TEMPLATES: tuple[str, ...] = (
    "Нанесение логотипа: {t}",
    "{t}: когда выбирать эту технологию",
    "{t} на изделиях — стойкость и детализация",
)

_CTA = "Заявка и расчёт тиража — в сообщениях группы или на сайте."


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _largest_remainder(content_mix: tuple[tuple[str, int], ...], days: int) -> dict[str, int]:
    """Распределить ``days`` по меткам пропорционально процентам (метод остатков)."""
    total = sum(pct for _, pct in content_mix) or 1
    exact = {label: days * pct / total for label, pct in content_mix}
    counts = {label: int(math.floor(value)) for label, value in exact.items()}
    remainder = days - sum(counts.values())
    order = sorted(
        content_mix,
        key=lambda item: (-(exact[item[0]] - math.floor(exact[item[0]])), item[0]),
    )
    for label, _ in order[:remainder]:
        counts[label] += 1
    return counts


def _spread_rubrics(content_mix: tuple[tuple[str, int], ...], days: int) -> list[str]:
    """Равномерно распределить рубрики по дням (интерливинг, детерминированно)."""
    counts = _largest_remainder(content_mix, days)
    slots: list[tuple[float, str]] = []
    for label, count in counts.items():
        for j in range(count):
            slots.append(((j + 0.5) / count, label))
    slots.sort(key=lambda item: (item[0], item[1]))
    return [label for _, label in slots][:days]


class SeoContentPlanService:
    """Строит SEO-контент-план проекта на N дней."""

    def build_plan(
        self, project_slug: str, days: int = 30, start_date: date | None = None
    ) -> SeoContentPlan:
        """Собрать контент-план. ``start_date`` по умолчанию — сегодня."""
        profile = get_project_seo_profile(project_slug)
        days = max(days, 1)
        start = start_date or date.today()
        warnings: list[str] = []

        product_queries = self._product_queries(profile)
        process_queries = self._process_queries(profile)
        technologies = [name for name, _ in profile.content_vector.priority_technologies]
        products = list(profile.catalog_products)

        if not product_queries and not products:
            warnings.append("Нет продуктов/запросов в профиле — план ограничен.")
        if not profile.site_url:
            warnings.append("У проекта не задан сайт — ссылки в плане пустые (плейсхолдер).")

        rubric_sequence = _spread_rubrics(profile.content_vector.content_mix, days)
        counters: dict[str, int] = {}
        items: list[SeoContentPlanItem] = []

        for day_index, label in enumerate(rubric_sequence):
            idx = counters.get(label, 0)
            counters[label] = idx + 1
            item = self._build_item(
                profile=profile,
                label=label,
                day_index=day_index,
                rubric_index=idx,
                start=start,
                product_queries=product_queries,
                process_queries=process_queries,
                technologies=technologies,
                products=products,
            )
            items.append(item)

        distribution: dict[str, int] = {}
        for item in items:
            distribution[item.rubric] = distribution.get(item.rubric, 0) + 1

        return SeoContentPlan(
            project_slug=project_slug,
            brand_name=profile.brand_name,
            site_url=profile.site_url,
            days=days,
            start_date=start.isoformat(),
            items=items,
            rubric_distribution=distribution,
            warnings=warnings,
        )

    # --- Наполнение одного дня ---

    def _build_item(
        self,
        *,
        profile: ProjectSeoProfile,
        label: str,
        day_index: int,
        rubric_index: int,
        start: date,
        product_queries: list[SeoQuery],
        process_queries: list[SeoQuery],
        technologies: list[str],
        products: list[str],
    ) -> SeoContentPlanItem:
        rubric = rubric_title(label)
        current = start + timedelta(days=day_index)
        weekday = _WEEKDAYS_RU[current.weekday()]

        if label == _TECHNOLOGIES and technologies:
            item = self._tech_item(profile, technologies, rubric_index)
        elif label == _PRODUCTION and (process_queries or product_queries):
            item = self._production_item(profile, process_queries or product_queries, rubric_index)
        elif label == _CASES and (product_queries or products):
            item = self._case_item(profile, product_queries, products, rubric_index)
        elif label == _FAQ and (product_queries or products):
            item = self._faq_item(profile, product_queries, products, rubric_index)
        elif product_queries:
            item = self._product_item(profile, product_queries, rubric_index)
        elif products:
            item = self._product_fallback_item(profile, products, rubric_index)
        else:
            item = self._generic_item(profile)

        topic, seo_query, frequency, product, technology, link, media_tag = item
        return SeoContentPlanItem(
            day_number=day_index + 1,
            date=current.isoformat(),
            weekday=weekday,
            rubric=rubric,
            topic=topic,
            seo_query=seo_query,
            seo_frequency=frequency,
            product=product,
            technology=technology,
            site_url=link.url if link else profile.site_url,
            site_page_title=link.title if link else "",
            media_tag=media_tag,
            cta=_CTA,
        )

    # Каждый handler возвращает кортеж:
    # (topic, seo_query, frequency, product, technology, SiteLink|None, media_tag)

    def _product_item(
        self, profile: ProjectSeoProfile, queries: list[SeoQuery], index: int
    ) -> tuple[str, str, int, str | None, str | None, SiteLink | None, str]:
        query = queries[index % len(queries)]
        product = query.product
        template = _PRODUCT_TOPIC_TEMPLATES[index % len(_PRODUCT_TOPIC_TEMPLATES)]
        topic = _cap(template.format(p=(product or "изделия")))
        link = select_site_link(
            profile.project_slug,
            seo_query=query.query,
            products=[product] if product else [],
        )
        media_tag = _PRODUCT_MEDIA_TAG.get(product or "", product or "мерч")
        return topic, query.query, query.frequency, product, None, link, media_tag

    def _tech_item(
        self, profile: ProjectSeoProfile, technologies: list[str], index: int
    ) -> tuple[str, str, int, str | None, str | None, SiteLink | None, str]:
        technology = technologies[index % len(technologies)]
        template = _TECH_TOPIC_TEMPLATES[index % len(_TECH_TOPIC_TEMPLATES)]
        topic = _cap(template.format(t=technology))
        media_tag = _TECHNOLOGY_MEDIA_TAG.get(technology, technology.lower())
        seo_query = f"нанесение логотипа {media_tag}"
        link = select_site_link(profile.project_slug, technologies=[technology])
        return topic, seo_query, 0, None, technology, link, media_tag

    def _production_item(
        self, profile: ProjectSeoProfile, queries: list[SeoQuery], index: int
    ) -> tuple[str, str, int, str | None, str | None, SiteLink | None, str]:
        query = queries[index % len(queries)]
        product = query.product
        topic = _cap(f"Собственный цех: {query.query}")
        link = select_site_link(
            profile.project_slug,
            seo_query=query.query,
            products=[product] if product else [],
        )
        media_tag = _PRODUCT_MEDIA_TAG.get(product or "", "цех")
        return topic, query.query, query.frequency, product, None, link, media_tag

    def _case_item(
        self,
        profile: ProjectSeoProfile,
        queries: list[SeoQuery],
        products: list[str],
        index: int,
    ) -> tuple[str, str, int, str | None, str | None, SiteLink | None, str]:
        product = self._pick_product(queries, products, index)
        topic = _cap(f"Кейс: корпоративный мерч — {product or 'под ключ'}")
        seo_query = f"{product} на заказ для компаний" if product else "мерч под ключ для компаний"
        portfolio = find_site_page(profile, "portfolio")
        link = (
            SiteLink(portfolio.url, portfolio.title, portfolio.page_type, "portfolio", "Кейс")
            if portfolio and portfolio.url
            else select_site_link(profile.project_slug, seo_query=seo_query)
        )
        media_tag = _PRODUCT_MEDIA_TAG.get(product or "", "кейс")
        return topic, seo_query, 0, product, None, link, media_tag

    def _faq_item(
        self,
        profile: ProjectSeoProfile,
        queries: list[SeoQuery],
        products: list[str],
        index: int,
    ) -> tuple[str, str, int, str | None, str | None, SiteLink | None, str]:
        product = self._pick_product(queries, products, index)
        subject = product or "мерч"
        topic = _cap(f"Как выбрать {subject}: материал, тираж, нанесение")
        seo_query = f"как выбрать {subject}"
        faq = find_site_page(profile, "faq")
        link = (
            SiteLink(faq.url, faq.title, faq.page_type, "faq", "FAQ")
            if faq and faq.url
            else select_site_link(profile.project_slug, seo_query=seo_query, products=[subject])
        )
        media_tag = _PRODUCT_MEDIA_TAG.get(product or "", "мерч")
        return topic, seo_query, 0, product, None, link, media_tag

    def _product_fallback_item(
        self, profile: ProjectSeoProfile, products: list[str], index: int
    ) -> tuple[str, str, int, str | None, str | None, SiteLink | None, str]:
        product = products[index % len(products)]
        topic = _cap(f"{product} на заказ")
        seo_query = f"{product} на заказ"
        link = select_site_link(profile.project_slug, seo_query=seo_query, products=[product])
        media_tag = _PRODUCT_MEDIA_TAG.get(product, product)
        return topic, seo_query, 0, product, None, link, media_tag

    def _generic_item(
        self, profile: ProjectSeoProfile
    ) -> tuple[str, str, int, str | None, str | None, SiteLink | None, str]:
        topic = f"{profile.brand_name}: корпоративный мерч под ключ"
        link = select_site_link(profile.project_slug, seo_query="мерч под ключ")
        return topic, "мерч под ключ", 0, None, None, link, "мерч"

    @staticmethod
    def _pick_product(queries: list[SeoQuery], products: list[str], index: int) -> str | None:
        products_from_queries = [q.product for q in queries if q.product]
        pool = list(dict.fromkeys(products_from_queries)) or products
        return pool[index % len(pool)] if pool else None

    @staticmethod
    def _product_queries(profile: ProjectSeoProfile) -> list[SeoQuery]:
        queries = [q for q in profile.seo_queries if q.product and q.intent != "process"]
        queries.sort(key=lambda q: (q.priority, q.frequency), reverse=True)
        return queries

    @staticmethod
    def _process_queries(profile: ProjectSeoProfile) -> list[SeoQuery]:
        queries = [q for q in profile.seo_queries if q.intent == "process"]
        queries.sort(key=lambda q: (q.priority, q.frequency), reverse=True)
        return queries
