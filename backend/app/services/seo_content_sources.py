"""SEO-источники проектов: сайт, каталог, брендирование, контент-вектор.

Модуль описывает СТРУКТУРУ SEO-профиля проекта и содержит заполненный профиль
TEEON (на основе сайта https://teeon.ru: каталог + раздел нанесений) и
плейсхолдер для второй группы «Фабрика сувениров» (project_slug=fabric-souvenirs).

Всё детерминировано и оффлайн: ни сети, ни AI, ни обращений к БД. URL страниц
сверены со структурой сайта teeon.ru (каталог ``/catalog/...``, нанесения
``/branding/...``). Технологии без отдельной страницы (например, УФ-печать и
термотрансфер) ведут на корневую страницу нанесений ``/branding``.

Данные отсюда используют:
- :mod:`app.services.site_link_selection_service` — выбор релевантной ссылки;
- :mod:`app.services.vk_group_seo_setup_service` — SEO-заполнение VK-группы;
- :mod:`app.services.seo_content_plan_service` — контент-план;
- CLI-скрипты и SEO-эндпоинты.

Seed-ядро SEO-запросов вынесено в :mod:`app.services.teeon_seo_queries` и
подключается лениво (во избежание циклического импорта).
"""

from dataclasses import dataclass, field
from functools import cache

# --- Структуры данных (иммутабельные, hashable — пригодны для кеширования) ---


@dataclass(frozen=True)
class Contacts:
    """Контакты проекта для футера постов и описания группы."""

    phone: str
    email: str
    city: str
    schedule: str
    website: str


@dataclass(frozen=True)
class SitePage:
    """Страница сайта проекта.

    ``page_type``: ``home`` | ``catalog`` | ``branding`` | ``portfolio`` |
    ``contacts`` | ``faq`` | ``landing`` | ``about``.

    ``keywords`` — токены/основы слов для сопоставления темы поста со страницей
    (учитывается частичное вхождение), ``products`` / ``technologies`` — какие
    изделия/технологии закрывает страница.
    """

    slug: str
    title: str
    url: str
    page_type: str
    keywords: tuple[str, ...] = ()
    products: tuple[str, ...] = ()
    technologies: tuple[str, ...] = ()
    audiences: tuple[str, ...] = ()
    priority: int = 0
    notes: str = ""


@dataclass(frozen=True)
class SeoQuery:
    """SEO-запрос из seed-ядра Яндекса.

    ``intent``: ``commercial`` | ``informational`` | ``brand`` | ``process`` |
    ``price``. ``frequency`` — частотность из выгрузки (может быть 0 —
    long-tail сохраняем). ``priority`` — производный вес (0..100).
    """

    query: str
    frequency: int
    cluster: str
    product: str | None = None
    technology: str | None = None
    intent: str = "commercial"
    priority: int = 0


@dataclass(frozen=True)
class ContentVector:
    """Контентный вектор публикаций проекта (приоритеты и тон)."""

    priority_products: tuple[tuple[str, int], ...]
    priority_technologies: tuple[tuple[str, int], ...]
    content_mix: tuple[tuple[str, int], ...]
    tone: tuple[str, ...]
    forbidden: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectSeoProfile:
    """SEO-профиль проекта (единый источник данных для SEO-модулей)."""

    project_slug: str
    brand_name: str
    site_url: str
    contacts: Contacts
    catalog_pages: tuple[SitePage, ...]
    branding_pages: tuple[SitePage, ...]
    seo_queries: tuple[SeoQuery, ...]
    priority_products: tuple[str, ...]
    priority_technologies: tuple[str, ...]
    content_vector: ContentVector
    vk_group_id: str | None = None
    vk_screen_name: str | None = None
    # Дополнительно (не входит в минимальную структуру, но нужно контенту).
    other_pages: tuple[SitePage, ...] = ()
    short_description: str = ""
    positioning: tuple[str, ...] = ()
    trust_facts: tuple[str, ...] = ()
    catalog_products: tuple[str, ...] = field(default_factory=tuple)


class UnknownSeoProjectError(Exception):
    """Для проекта нет SEO-профиля."""

    def __init__(self, project_slug: str) -> None:
        self.project_slug = project_slug
        super().__init__(f"SEO-профиль для проекта '{project_slug}' не задан")


# --- TEEON: контакты, сайт, каталог, нанесения ---

_TEEON_CONTACTS = Contacts(
    phone="+7 (495) 152-37-45",
    email="teeon@upgifts.ru",
    city="Москва",
    schedule="Пн–Пт, 10:00–19:00",
    website="https://teeon.ru",
)

_TEEON_POSITIONING: tuple[str, ...] = (
    "Производство корпоративного мерча и промо-одежды на заказ.",
    "Собственный швейный цех в Москве.",
    "Полный цикл: идея → дизайн → персонализация → пошив → упаковка → поставка.",
    "Работа с юрлицами по договору.",
    "Доставка по России.",
)

_TEEON_TRUST_FACTS: tuple[str, ...] = (
    "Собственное производство 1000 м².",
    "На рынке с 2018 года.",
    "3000+ реализованных кейсов.",
    "50 промышленных машин Juki.",
    "15+ станков персонализации.",
)

_TEEON_SHORT_DESCRIPTION = (
    "TEEON — производство корпоративного мерча и промо-одежды на заказ: футболки, "
    "худи, свитшоты, лонгсливы, кепки, жилетки, куртки, дождевики и сумки с "
    "нанесением логотипа. Собственный швейный цех в Москве, работа с юрлицами, "
    "доставка по России."
)

# Каталог. URL сверены со структурой сайта teeon.ru.
_TEEON_CATALOG_PAGES: tuple[SitePage, ...] = (
    SitePage(
        slug="futbolki",
        title="Футболки на заказ",
        url="https://teeon.ru/catalog/futbolki",
        page_type="catalog",
        keywords=("футболк", "майк", "маек", "промо футболк", "сигнальн"),
        products=("футболки", "футболка", "майки", "майка"),
        priority=100,
    ),
    SitePage(
        slug="hudi",
        title="Худи на заказ",
        url="https://teeon.ru/catalog/hudi",
        page_type="catalog",
        keywords=("худи", "толстовк", "зип худи", "зип толстовк"),
        products=("худи", "толстовки", "толстовка"),
        priority=95,
    ),
    SitePage(
        slug="svitshoty",
        title="Свитшоты на заказ",
        url="https://teeon.ru/catalog/svitshoty",
        page_type="catalog",
        keywords=("свитшот",),
        products=("свитшоты", "свитшот"),
        priority=80,
    ),
    SitePage(
        slug="longslivy",
        title="Лонгсливы на заказ",
        url="https://teeon.ru/catalog/longslivy",
        page_type="catalog",
        keywords=("лонгслив",),
        products=("лонгсливы", "лонгслив"),
        priority=80,
    ),
    SitePage(
        slug="kepki",
        title="Кепки и бейсболки на заказ",
        url="https://teeon.ru/catalog/kepki",
        page_type="catalog",
        keywords=("кепк", "кепок", "бейсболк"),
        products=("кепки", "кепка", "бейсболки", "бейсболка"),
        priority=75,
    ),
    SitePage(
        slug="zhiletki",
        title="Жилетки на заказ",
        url="https://teeon.ru/catalog/zhiletki",
        page_type="catalog",
        keywords=("жилет", "стеган"),
        products=("жилетки", "жилетка", "жилеты", "жилет"),
        priority=70,
    ),
    SitePage(
        slug="kurtki",
        title="Куртки на заказ",
        url="https://teeon.ru/catalog/kurtki",
        page_type="catalog",
        keywords=("куртк", "курток", "спецодежд"),
        products=("куртки", "куртка"),
        priority=65,
    ),
    SitePage(
        slug="dozhdeviki",
        title="Дождевики на заказ",
        url="https://teeon.ru/catalog/dozhdeviki",
        page_type="catalog",
        keywords=("дождевик", "дождевики eva", "ева"),
        products=("дождевики", "дождевик"),
        priority=60,
    ),
    SitePage(
        slug="sumki",
        title="Сумки и шопперы на заказ",
        url="https://teeon.ru/catalog/sumki",
        page_type="catalog",
        keywords=("сумк", "сумок", "шоппер", "шопер"),
        products=("сумки", "сумка", "шопперы", "шоппер"),
        priority=55,
    ),
)

# Нанесение / брендирование. У УФ-печати и термотрансфера нет отдельной страницы
# на сайте — они ведут на корневую /branding (см. other_pages → branding).
_TEEON_BRANDING_PAGES: tuple[SitePage, ...] = (
    SitePage(
        slug="dtf-pechat",
        title="DTF-печать",
        url="https://teeon.ru/branding/dtf-pechat",
        page_type="branding",
        keywords=("dtf",),
        technologies=("dtf", "dtf-печать", "dtf печать"),
        priority=100,
    ),
    SitePage(
        slug="vyshivka",
        title="Вышивка логотипа",
        url="https://teeon.ru/branding/vyshivka",
        page_type="branding",
        keywords=("вышивк",),
        technologies=("вышивка",),
        priority=95,
    ),
    SitePage(
        slug="gravirovka",
        title="Лазерная гравировка",
        url="https://teeon.ru/branding/gravirovka",
        page_type="branding",
        keywords=("гравировк",),
        technologies=("гравировка",),
        priority=90,
    ),
    SitePage(
        slug="shelkografiya",
        title="Шелкография",
        url="https://teeon.ru/branding/shelkografiya",
        page_type="branding",
        keywords=("шелкограф",),
        technologies=("шелкография",),
        priority=85,
    ),
    SitePage(
        slug="dtg-pechat",
        title="DTG-печать",
        url="https://teeon.ru/branding/dtg-pechat",
        page_type="branding",
        keywords=("dtg",),
        technologies=("dtg", "dtg-печать"),
        priority=75,
    ),
    SitePage(
        slug="shevrony",
        title="Шевроны и нашивки",
        url="https://teeon.ru/branding/shevrony",
        page_type="branding",
        keywords=("шеврон", "нашивк"),
        technologies=("шевроны", "шеврон"),
        priority=65,
    ),
    SitePage(
        slug="birki",
        title="Бирки и лейблы",
        url="https://teeon.ru/branding/birki",
        page_type="branding",
        keywords=("бирк", "лейбл", "этикетк"),
        technologies=("бирки", "бирка", "лейблы", "лейбл", "бирки / лейблы"),
        priority=60,
    ),
)

# Прочие важные страницы (главная, разделы-«зонтики», доверие).
_TEEON_OTHER_PAGES: tuple[SitePage, ...] = (
    SitePage(
        slug="home",
        title="TEEON — производство корпоративного мерча",
        url="https://teeon.ru",
        page_type="home",
        keywords=("teeon", "тион"),
        priority=100,
    ),
    SitePage(
        slug="catalog",
        title="Каталог изделий",
        url="https://teeon.ru/catalog",
        page_type="catalog",
        keywords=("каталог", "изделия", "одежда"),
        priority=90,
    ),
    SitePage(
        slug="branding",
        title="Нанесение логотипа",
        url="https://teeon.ru/branding",
        page_type="branding",
        keywords=(
            "нанесение",
            "нанесение логотипа",
            "брендирование",
            "уф-печат",
            "уф печат",
            "термотрансфер",
            "сублимац",
            "тиснен",
        ),
        technologies=("уф-печать", "термотрансфер", "сублимация", "тиснение"),
        priority=90,
        notes="Технологии без отдельной страницы (УФ-печать, термотрансфер) ведут сюда.",
    ),
    SitePage(
        slug="korporativnyy-merch",
        title="Корпоративный мерч под ключ",
        url="https://teeon.ru/korporativnyy-merch",
        page_type="landing",
        keywords=(
            "мерч",
            "мерч под ключ",
            "корпоративн",
            "корпоративная одежда",
            "промо-одежда",
            "промоодежда",
            "welcome",
        ),
        products=("мерч", "корпоративная одежда", "промо-одежда"),
        priority=85,
    ),
    SitePage(
        slug="portfolio",
        title="Портфолио и кейсы",
        url="https://teeon.ru/portfolio",
        page_type="portfolio",
        keywords=("портфолио", "кейс", "кейсы", "примеры", "работы"),
        priority=70,
    ),
    SitePage(
        slug="about",
        title="О производстве",
        url="https://teeon.ru/about",
        page_type="about",
        keywords=("производство", "пошив", "цех", "о компании", "фабрика"),
        priority=60,
    ),
    SitePage(
        slug="contacts",
        title="Контакты",
        url="https://teeon.ru/contacts",
        page_type="contacts",
        keywords=("контакты", "адрес", "связаться", "заявк"),
        priority=50,
    ),
    SitePage(
        slug="faq",
        title="Вопросы и ответы",
        url="https://teeon.ru/faq",
        page_type="faq",
        keywords=("faq", "вопрос", "как выбрать", "как заказать"),
        priority=50,
    ),
)

# Приоритет ПРОДУКТОВ (Задача 6): изделия и их вес 0..100.
_TEEON_PRIORITY_PRODUCTS: tuple[tuple[str, int], ...] = (
    ("футболки", 100),
    ("худи", 95),
    ("свитшоты", 80),
    ("лонгсливы", 80),
    ("кепки", 75),
    ("жилетки", 70),
    ("куртки", 65),
    ("дождевики", 60),
    ("сумки", 55),
)

# Приоритет ТЕХНОЛОГИЙ (Задача 6). УФ-печать заложена приоритетной по требованию
# владельца, даже если на текущих страницах сайта представлена слабо.
_TEEON_PRIORITY_TECHNOLOGIES: tuple[tuple[str, int], ...] = (
    ("DTF-печать", 100),
    ("вышивка", 95),
    ("гравировка", 90),
    ("УФ-печать", 90),
    ("шелкография", 85),
    ("DTG-печать", 75),
    ("термотрансфер", 70),
    ("шевроны", 65),
    ("бирки / лейблы", 60),
)

_TEEON_CONTENT_MIX: tuple[tuple[str, int], ...] = (
    ("товары/изделия", 30),
    ("технологии нанесения", 30),
    ("производство/процесс", 20),
    ("кейсы/портфолио", 10),
    ("FAQ/обучение/как выбрать", 10),
)

_TEEON_TONE: tuple[str, ...] = (
    "B2B",
    "экспертный",
    "уверенный",
    "без хайпа",
    "акцент на качество, сроки, тиражи, производство, договор, расчёт стоимости",
)

_TEEON_FORBIDDEN: tuple[str, ...] = (
    "выдавать внешние картинки за свои кейсы",
    "обещать невозможные сроки",
    "искажать цвет/фактуру изделий",
    "публиковать без review",
    "включать live-publishing по умолчанию",
)

_TEEON_CONTENT_VECTOR = ContentVector(
    priority_products=_TEEON_PRIORITY_PRODUCTS,
    priority_technologies=_TEEON_PRIORITY_TECHNOLOGIES,
    content_mix=_TEEON_CONTENT_MIX,
    tone=_TEEON_TONE,
    forbidden=_TEEON_FORBIDDEN,
)


# --- Фабрика сувениров: плейсхолдер под вторую группу (Задача 8) ---

_FABRIC_CONTACTS = Contacts(
    phone="+7 (495) 152-37-45",
    email="teeon@upgifts.ru",
    city="Москва",
    schedule="Пн–Пт, 10:00–19:00",
    website="",
)

_FABRIC_CONTENT_VECTOR = ContentVector(
    priority_products=(
        ("кружки", 100),
        ("ручки", 90),
        ("текстиль", 85),
        ("пакеты", 70),
        ("корпоративные подарки", 65),
    ),
    priority_technologies=(
        ("УФ-печать", 100),
        ("шелкография", 90),
        ("тампопечать", 85),
        ("гравировка", 80),
        ("вышивка", 60),
    ),
    content_mix=(
        ("товары/сувениры", 35),
        ("технологии нанесения", 30),
        ("производство/процесс", 15),
        ("кейсы/подарочные наборы", 10),
        ("FAQ/как выбрать", 10),
    ),
    tone=(
        "B2B",
        "экспертный",
        "уверенный",
        "без хайпа",
        "акцент на брендирование, тиражи, сроки, договор",
    ),
    forbidden=_TEEON_FORBIDDEN,
)


def _teeon_profile() -> ProjectSeoProfile:
    """Собрать SEO-профиль TEEON (SEO-запросы подключаются лениво)."""
    # Ленивый импорт исключает цикл: teeon_seo_queries → seo_content_sources.
    from app.services.teeon_seo_queries import build_teeon_seo_queries

    return ProjectSeoProfile(
        project_slug="teeon",
        brand_name="TEEON",
        site_url="https://teeon.ru",
        contacts=_TEEON_CONTACTS,
        catalog_pages=_TEEON_CATALOG_PAGES,
        branding_pages=_TEEON_BRANDING_PAGES,
        seo_queries=build_teeon_seo_queries(),
        priority_products=tuple(name for name, _ in _TEEON_PRIORITY_PRODUCTS),
        priority_technologies=tuple(name for name, _ in _TEEON_PRIORITY_TECHNOLOGIES),
        content_vector=_TEEON_CONTENT_VECTOR,
        vk_group_id="240102732",
        vk_screen_name="teeon",
        other_pages=_TEEON_OTHER_PAGES,
        short_description=_TEEON_SHORT_DESCRIPTION,
        positioning=_TEEON_POSITIONING,
        trust_facts=_TEEON_TRUST_FACTS,
        catalog_products=(
            "футболки",
            "худи",
            "свитшоты",
            "лонгсливы",
            "кепки",
            "жилетки",
            "куртки",
            "дождевики",
            "сумки",
        ),
    )


def _fabric_souvenirs_profile() -> ProjectSeoProfile:
    """Плейсхолдер SEO-профиля «Фабрика сувениров» (архитектура под 2-ю группу).

    Полный контент пока не заполняется — задан минимальный каркас: контакты,
    контент-вектор, приоритеты. Публикация в эту группу на данном этапе не ведётся.
    """
    home = SitePage(
        slug="home",
        title="Фабрика сувениров — корпоративные подарки и сувениры",
        url="",
        page_type="home",
        keywords=("сувенир", "подарк", "фабрика сувениров"),
        priority=100,
    )
    return ProjectSeoProfile(
        project_slug="fabric-souvenirs",
        brand_name="Фабрика сувениров",
        site_url="",
        contacts=_FABRIC_CONTACTS,
        catalog_pages=(),
        branding_pages=(),
        seo_queries=(),
        priority_products=tuple(name for name, _ in _FABRIC_CONTENT_VECTOR.priority_products),
        priority_technologies=tuple(
            name for name, _ in _FABRIC_CONTENT_VECTOR.priority_technologies
        ),
        content_vector=_FABRIC_CONTENT_VECTOR,
        vk_group_id=None,
        vk_screen_name=None,
        other_pages=(home,),
        short_description=(
            "Фабрика сувениров — производство и брендирование сувенирной продукции: "
            "кружки, ручки, текстиль, пакеты и корпоративные подарки с нанесением "
            "логотипа (УФ-печать, шелкография, тампопечать, гравировка)."
        ),
        positioning=("Производство и брендирование сувенирной продукции.",),
        trust_facts=(),
        catalog_products=("кружки", "ручки", "текстиль", "пакеты", "корпоративные подарки"),
    )


_PROFILE_BUILDERS = {
    "teeon": _teeon_profile,
    "fabric-souvenirs": _fabric_souvenirs_profile,
}


@cache
def get_project_seo_profile(project_slug: str) -> ProjectSeoProfile:
    """Вернуть SEO-профиль проекта. UnknownSeoProjectError, если профиля нет."""
    builder = _PROFILE_BUILDERS.get(project_slug)
    if builder is None:
        raise UnknownSeoProjectError(project_slug)
    return builder()


def list_supported_seo_projects() -> tuple[str, ...]:
    """Список project_slug, для которых есть SEO-профиль."""
    return tuple(_PROFILE_BUILDERS)


def all_site_pages(profile: ProjectSeoProfile) -> tuple[SitePage, ...]:
    """Все страницы профиля (каталог + нанесения + прочие) одним списком."""
    return (*profile.catalog_pages, *profile.branding_pages, *profile.other_pages)


def find_site_page(profile: ProjectSeoProfile, slug: str) -> SitePage | None:
    """Найти страницу профиля по slug (или None)."""
    for page in all_site_pages(profile):
        if page.slug == slug:
            return page
    return None


def rubric_title(label: str) -> str:
    """Читаемая рубрика из метки контент-микса (``товары/изделия`` → ``Товары и изделия``)."""
    parts = [part.strip() for part in label.split("/") if part.strip()]
    joined = " и ".join(parts) if len(parts) == 2 else ", ".join(parts)
    return joined[:1].upper() + joined[1:] if joined else label


def get_default_publication_vector(project_slug: str) -> dict[str, int]:
    """Дефолтный бизнес-вектор публикаций из SEO-профиля (продукты + технологии).

    Ключи — направления (изделия и технологии), значения — вес приоритета 0..100.
    Используется флагом ``--use-default-publication-vector`` и SEO-эндпоинтами.
    """
    profile = get_project_seo_profile(project_slug)
    vector: dict[str, int] = {}
    for name, weight in profile.content_vector.priority_products:
        vector[name] = weight
    for name, weight in profile.content_vector.priority_technologies:
        vector.setdefault(name, weight)
    return vector
