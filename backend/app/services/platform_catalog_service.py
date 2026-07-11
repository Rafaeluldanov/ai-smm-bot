"""Единый каталог медиа-платформ Botfleet (Россия + международные площадки).

Описывает КАЖДУЮ площадку декларативно: категория, уровень поддержки, что уже умеет
(публикация/расписание/аналитика/медиа), нужна ли публичная ссылка на медиа, короткое
описание и оригинальная inline SVG-иконка (не официальный логотип).

Каталог — единственный источник правды для дашборда, страниц платформ и справки. Он НЕ
делает сетевых вызовов и не хранит секретов.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.services.platform_icons import platform_icon_svg

# Категории площадок.
CATEGORY_MESSENGER = "messenger"
CATEGORY_SOCIAL = "social"
CATEGORY_VIDEO = "video"
CATEGORY_BLOG = "blog"
CATEGORY_MARKETPLACE = "marketplace"
CATEGORY_STORAGE = "storage"
CATEGORY_WEBSITE = "website"
CATEGORY_EMAIL = "email"
CATEGORY_BUSINESS_DIRECTORY = "business_directory"

CATEGORIES: tuple[str, ...] = (
    CATEGORY_MESSENGER,
    CATEGORY_SOCIAL,
    CATEGORY_VIDEO,
    CATEGORY_BLOG,
    CATEGORY_MARKETPLACE,
    CATEGORY_STORAGE,
    CATEGORY_WEBSITE,
    CATEGORY_EMAIL,
    CATEGORY_BUSINESS_DIRECTORY,
)
_CATEGORY_TITLES: dict[str, str] = {
    CATEGORY_MESSENGER: "Мессенджеры",
    CATEGORY_SOCIAL: "Соцсети",
    CATEGORY_VIDEO: "Видео",
    CATEGORY_BLOG: "Блоги и медиа",
    CATEGORY_MARKETPLACE: "Маркетплейсы",
    CATEGORY_STORAGE: "Хранилища медиа",
    CATEGORY_WEBSITE: "Сайт",
    CATEGORY_EMAIL: "E-mail",
    CATEGORY_BUSINESS_DIRECTORY: "Бизнес-справочники",
}

# Уровни поддержки (в порядке готовности).
SUPPORT_ACTIVE = "active"
SUPPORT_BETA = "beta"
SUPPORT_PLANNED = "planned"
SUPPORT_RESEARCH = "research"
SUPPORT_LEVELS: tuple[str, ...] = (SUPPORT_ACTIVE, SUPPORT_BETA, SUPPORT_PLANNED, SUPPORT_RESEARCH)
_SUPPORT_ORDER = {level: i for i, level in enumerate(SUPPORT_LEVELS)}
_SUPPORT_TITLES: dict[str, str] = {
    SUPPORT_ACTIVE: "Активна",
    SUPPORT_BETA: "Скоро",
    SUPPORT_PLANNED: "В планах",
    SUPPORT_RESEARCH: "Исследуем",
}
# Планируемые уровни (интеграция ещё в разработке).
PLANNED_LEVELS: tuple[str, ...] = (SUPPORT_PLANNED, SUPPORT_RESEARCH)


@dataclass(frozen=True)
class PlatformCatalogItem:
    """Описание одной площадки в каталоге Botfleet."""

    key: str
    title_ru: str
    title_en: str
    category: str
    support_level: str
    can_publish: bool
    can_schedule: bool
    can_analytics: bool
    can_media: bool
    requires_public_media_url: bool
    notes_short: str
    guide_anchor: str
    accent_class: str
    icon_svg: str = field(default="", repr=False)

    @property
    def support_title(self) -> str:
        return _SUPPORT_TITLES.get(self.support_level, self.support_level)

    @property
    def category_title(self) -> str:
        return _CATEGORY_TITLES.get(self.category, self.category)

    @property
    def is_planned(self) -> bool:
        """Площадка ещё в разработке (planned/research) — live-действия выключены."""
        return self.support_level in PLANNED_LEVELS


def _item(
    key: str,
    title_ru: str,
    title_en: str,
    category: str,
    support_level: str,
    notes_short: str,
    *,
    can_publish: bool = False,
    can_schedule: bool = False,
    can_analytics: bool = True,
    can_media: bool = False,
    requires_public_media_url: bool = False,
    guide_anchor: str | None = None,
) -> PlatformCatalogItem:
    return PlatformCatalogItem(
        key=key,
        title_ru=title_ru,
        title_en=title_en,
        category=category,
        support_level=support_level,
        can_publish=can_publish,
        can_schedule=can_schedule,
        can_analytics=can_analytics,
        can_media=can_media,
        requires_public_media_url=requires_public_media_url,
        notes_short=notes_short,
        guide_anchor=guide_anchor or key,
        accent_class=f"accent-{key}",
        icon_svg=platform_icon_svg(key),
    )


# Каталог платформ. Порядок — как в определении (далее сортируется по уровню поддержки).
_CATALOG: tuple[PlatformCatalogItem, ...] = (
    # --- Активные / основные ---
    _item(
        "telegram",
        "Telegram",
        "Telegram",
        CATEGORY_MESSENGER,
        SUPPORT_ACTIVE,
        "Текст и фото, media-group. Бот-администратор канала + токен.",
        can_publish=True,
        can_schedule=True,
        can_media=True,
    ),
    _item(
        "vk",
        "ВКонтакте",
        "VK",
        CATEGORY_SOCIAL,
        SUPPORT_ACTIVE,
        "Текст по ключу сообщества; фото — по личному user-token (OAuth).",
        can_publish=True,
        can_schedule=True,
        can_media=True,
    ),
    _item(
        "instagram",
        "Instagram",
        "Instagram",
        CATEGORY_SOCIAL,
        SUPPORT_ACTIVE,
        "Публикация через Meta Graph API; нужен публичный HTTPS image_url.",
        can_publish=True,
        can_schedule=True,
        can_media=True,
        requires_public_media_url=True,
    ),
    _item(
        "website",
        "Сайт",
        "Website",
        CATEGORY_WEBSITE,
        SUPPORT_ACTIVE,
        "Витрина/лендинг проекта: ссылка и SEO-контекст для кросс-постинга.",
        can_publish=False,
        can_schedule=False,
        can_analytics=True,
    ),
    _item(
        "yandex_disk",
        "Яндекс Диск",
        "Yandex Disk",
        CATEGORY_STORAGE,
        SUPPORT_ACTIVE,
        "Источник медиа: папки и теги; HEIC→JPEG. Не публикует сам.",
        can_publish=False,
        can_schedule=False,
        can_analytics=False,
        can_media=True,
    ),
    # --- Ближайшие (beta) ---
    _item(
        "youtube",
        "YouTube",
        "YouTube",
        CATEGORY_VIDEO,
        SUPPORT_BETA,
        "Видео и Shorts. Адаптер-скелет, live-загрузка готовится.",
        can_media=True,
    ),
    _item(
        "rutube",
        "RuTube",
        "RuTube",
        CATEGORY_VIDEO,
        SUPPORT_BETA,
        "Российское видео. Адаптер-скелет, публикация готовится.",
        can_media=True,
    ),
    _item(
        "dzen",
        "Дзен",
        "Dzen",
        CATEGORY_BLOG,
        SUPPORT_BETA,
        "Статьи и посты Дзена. Публикация по API готовится.",
    ),
    _item(
        "odnoklassniki",
        "Одноклассники",
        "OK",
        CATEGORY_SOCIAL,
        SUPPORT_BETA,
        "Посты и фото в ОК. Подключение по токену готовится.",
        can_media=True,
    ),
    _item(
        "google_drive",
        "Google Drive",
        "Google Drive",
        CATEGORY_STORAGE,
        SUPPORT_BETA,
        "Альтернативный источник медиа. Интеграция готовится.",
        can_analytics=False,
        can_media=True,
    ),
    # --- Планируемые ---
    _item(
        "facebook_page",
        "Facebook (страница)",
        "Facebook Page",
        CATEGORY_SOCIAL,
        SUPPORT_PLANNED,
        "Публикация на страницу через Meta Graph API. В планах.",
        can_media=True,
        requires_public_media_url=True,
    ),
    _item(
        "tiktok",
        "TikTok",
        "TikTok",
        CATEGORY_VIDEO,
        SUPPORT_PLANNED,
        "Короткие видео. Интеграция в планах.",
        can_media=True,
    ),
    _item(
        "pinterest",
        "Pinterest",
        "Pinterest",
        CATEGORY_SOCIAL,
        SUPPORT_PLANNED,
        "Пины и доски, визуальный трафик. В планах.",
        can_media=True,
        requires_public_media_url=True,
    ),
    _item(
        "tenchat",
        "TenChat",
        "TenChat",
        CATEGORY_SOCIAL,
        SUPPORT_PLANNED,
        "Деловая сеть: посты и нетворкинг. В планах.",
    ),
    _item(
        "vc_ru",
        "VC.ru",
        "VC.ru",
        CATEGORY_BLOG,
        SUPPORT_PLANNED,
        "Лонгриды и статьи для бизнес-аудитории. В планах.",
    ),
    _item(
        "linkedin",
        "LinkedIn",
        "LinkedIn",
        CATEGORY_SOCIAL,
        SUPPORT_PLANNED,
        "Международная деловая сеть. В планах.",
    ),
    _item(
        "email",
        "E-mail рассылки",
        "Email",
        CATEGORY_EMAIL,
        SUPPORT_PLANNED,
        "Письма и дайджесты по базе подписчиков. В планах.",
    ),
    _item(
        "blog_cms",
        "Блог / CMS",
        "Blog / CMS",
        CATEGORY_BLOG,
        SUPPORT_PLANNED,
        "Свой блог/CMS (WordPress и др.) по API. В планах.",
        requires_public_media_url=True,
    ),
    _item(
        "whatsapp_business",
        "WhatsApp Business",
        "WhatsApp Business",
        CATEGORY_MESSENGER,
        SUPPORT_PLANNED,
        "Рассылки и сообщения через WhatsApp Business API. В планах.",
    ),
    _item(
        "two_gis",
        "2ГИС",
        "2GIS",
        CATEGORY_BUSINESS_DIRECTORY,
        SUPPORT_PLANNED,
        "Карточка организации в справочнике 2ГИС. В планах.",
    ),
    _item(
        "avito",
        "Авито",
        "Avito",
        CATEGORY_MARKETPLACE,
        SUPPORT_PLANNED,
        "Объявления и магазин на Авито. В планах.",
        can_media=True,
    ),
    # --- Исследуем (research) ---
    _item(
        "pikabu",
        "Пикабу",
        "Pikabu",
        CATEGORY_BLOG,
        SUPPORT_RESEARCH,
        "Посты для широкой аудитории. Исследуем возможность.",
        can_media=True,
    ),
    _item(
        "x_twitter",
        "X (Twitter)",
        "X (Twitter)",
        CATEGORY_SOCIAL,
        SUPPORT_RESEARCH,
        "Короткие посты. Исследуем доступность API.",
    ),
    _item(
        "threads",
        "Threads",
        "Threads",
        CATEGORY_SOCIAL,
        SUPPORT_RESEARCH,
        "Текстовая соцсеть Meta. Исследуем возможность.",
    ),
)

_BY_KEY: dict[str, PlatformCatalogItem] = {item.key: item for item in _CATALOG}


class PlatformCatalogService:
    """Доступ к каталогу платформ: список, поиск, группировка, иконки."""

    def items(self) -> list[PlatformCatalogItem]:
        """Все площадки в порядке готовности (active → beta → planned → research)."""
        return sorted(
            _CATALOG,
            key=lambda i: (_SUPPORT_ORDER.get(i.support_level, 99), i.title_ru.lower()),
        )

    def get(self, key: str) -> PlatformCatalogItem | None:
        """Вернуть площадку по ключу (или None)."""
        return _BY_KEY.get((key or "").strip().lower())

    def keys(self) -> list[str]:
        """Ключи всех площадок."""
        return [item.key for item in self.items()]

    def icon_svg(self, key: str) -> str:
        """Оригинальная inline SVG-иконка площадки (или запасная)."""
        return platform_icon_svg((key or "").strip().lower())

    def label(self, key: str) -> str:
        """Русское название площадки (или сам ключ)."""
        item = self.get(key)
        return item.title_ru if item is not None else key

    def dashboard_items(self) -> list[PlatformCatalogItem]:
        """Площадки для дашборда проекта (весь каталог по готовности)."""
        return self.items()

    def planned_items(self) -> list[PlatformCatalogItem]:
        """Площадки в разработке (planned/research) — live-действия выключены."""
        return [i for i in self.items() if i.is_planned]

    def active_items(self) -> list[PlatformCatalogItem]:
        """Активные площадки (support_level=active)."""
        return [i for i in self.items() if i.support_level == SUPPORT_ACTIVE]

    def by_category(self) -> dict[str, list[PlatformCatalogItem]]:
        """Площадки, сгруппированные по категориям (в порядке CATEGORIES)."""
        grouped: dict[str, list[PlatformCatalogItem]] = {c: [] for c in CATEGORIES}
        for item in self.items():
            grouped.setdefault(item.category, []).append(item)
        return {c: grouped[c] for c in CATEGORIES if grouped.get(c)}

    @staticmethod
    def category_title(category: str) -> str:
        return _CATEGORY_TITLES.get(category, category)

    @staticmethod
    def as_dict(item: PlatformCatalogItem) -> dict[str, Any]:
        """Сериализовать площадку в dict (для API/JSON), без иконки-строки."""
        data = asdict(item)
        data.pop("icon_svg", None)
        data["support_title"] = item.support_title
        data["category_title"] = item.category_title
        data["is_planned"] = item.is_planned
        return data


def get_platform_catalog_service() -> PlatformCatalogService:
    """DI-фабрика каталога платформ."""
    return PlatformCatalogService()
