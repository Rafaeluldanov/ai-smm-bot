"""Схемы форм подключения платформ (для self-service UI).

Отдаёт декларативное описание формы подключения каждой платформы: поля (в т. ч.
секретные), шаги безопасной проверки, требования и предупреждения. Ничего не хранит и
не вызывает сеть — только описание. Используется UI и API `.../schema`.

Секретные поля помечены ``secret=True`` — их значение НИКОГДА не возвращается назад:
UI отправляет секрет write-only, а показывает только маску.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.services.platform_catalog_service import PlatformCatalogService

# Типы полей формы подключения.
FIELD_TEXT = "text"
FIELD_SECRET = "secret"
FIELD_URL = "url"
FIELD_LIST = "list"
FIELD_BOOL = "bool"
FIELD_SELECT = "select"


@dataclass(frozen=True)
class ConnectionField:
    """Одно поле формы подключения."""

    name: str
    label: str
    type: str = FIELD_TEXT
    required: bool = False
    placeholder: str = ""
    help: str = ""
    secret: bool = False
    masked: bool = False


@dataclass(frozen=True)
class PlatformConnectionSchema:
    """Полное описание формы подключения платформы."""

    platform_key: str
    title: str
    description: str
    support_level: str
    live_supported: bool
    fields: list[ConnectionField] = field(default_factory=list)
    test_steps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    media_requirements: str = ""
    guide_anchor: str = ""
    help_url: str = ""

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


def _f(name: str, label: str, **kwargs: Any) -> ConnectionField:
    return ConnectionField(name=name, label=label, **kwargs)


# Общие поля-заготовки.
def _title_field() -> ConnectionField:
    return _f(
        "title",
        "Название подключения",
        placeholder="Например: Основной канал",
        help="Понятное имя для этого подключения в проекте.",
    )


def _tags_field() -> ConnectionField:
    return _f(
        "tags", "Медиа-теги", type=FIELD_LIST, help="Через запятую — по каким тегам брать медиа."
    )


_CATALOG = PlatformCatalogService()


def _telegram_schema() -> tuple[list[ConnectionField], list[str], list[str], str]:
    fields = [
        _title_field(),
        _f(
            "api_key",
            "Bot token",
            type=FIELD_SECRET,
            required=True,
            secret=True,
            masked=True,
            placeholder="123456:ABC-DEF...",
            help="Токен бота из @BotFather.",
        ),
        _f(
            "external_id",
            "Channel username или ID",
            required=True,
            placeholder="@my_channel или -100123456789",
            help="Публичный @username канала или числовой id (-100…).",
        ),
        _tags_field(),
    ]
    steps = [
        "getMe — токен валиден",
        "getChat — канал доступен боту",
        "getChatMember — бот админ с правом постить",
    ]
    warnings = [
        "Бот должен быть администратором канала с правом «Публикация сообщений».",
        "Ошибка «chat not found» — неверный @username или бот не в канале.",
    ]
    return fields, steps, warnings, "Фото уходит в составе медиа-группы; HEIC→JPEG конвертируется."


def _vk_schema() -> tuple[list[ConnectionField], list[str], list[str], str]:
    fields = [
        _title_field(),
        _f(
            "api_key",
            "Access token",
            type=FIELD_SECRET,
            required=True,
            secret=True,
            masked=True,
            placeholder="vk1.a...",
            help="Токен сообщества (text-only) или личный user-token (фото).",
        ),
        _f(
            "external_id",
            "Group ID",
            required=True,
            placeholder="123456789",
            help="ID сообщества VK.",
        ),
        _f(
            "app_id",
            "App ID (OAuth, опц.)",
            placeholder="54671660",
            help="ID Standalone-приложения VK для OAuth.",
        ),
        _f(
            "app_secret",
            "App Secret (OAuth, опц.)",
            type=FIELD_SECRET,
            secret=True,
            masked=True,
            help="Секрет приложения VK (не показывается).",
        ),
        _f(
            "redirect_uri",
            "Redirect URI (OAuth, опц.)",
            type=FIELD_URL,
            help="Доверенный HTTPS Redirect URL для VK ID.",
        ),
        _tags_field(),
    ]
    steps = [
        "groups.getById — сообщество существует",
        "users.get — токен пользовательский (для фото)",
        "groups.get filter=admin — есть права администратора",
        "photos.getWallUploadServer / album probe — можно грузить фото (read-only проба)",
    ]
    warnings = [
        "Токен сообщества обычно работает text-only; для фото нужен личный user-token.",
        "Ошибка 27 (Group authorization failed) — токен не того типа или без прав photos.*.",
        "VK ID требует публичный HTTPS-домен в доверенных Redirect URL.",
    ]
    return fields, steps, warnings, "Фото через API требуют user-token владельца/админа."


def _instagram_schema() -> tuple[list[ConnectionField], list[str], list[str], str]:
    fields = [
        _title_field(),
        _f(
            "api_key",
            "Access token",
            type=FIELD_SECRET,
            required=True,
            secret=True,
            masked=True,
            help="Долгоживущий Access Token (Meta Graph API).",
        ),
        _f(
            "external_id",
            "Instagram User ID",
            required=True,
            placeholder="1784...",
            help="ID Instagram-аккаунта (professional).",
        ),
        _f("app_id", "App ID (опц.)", help="ID приложения Meta."),
        _f(
            "app_secret",
            "App Secret (опц.)",
            type=FIELD_SECRET,
            secret=True,
            masked=True,
            help="Секрет приложения Meta (не показывается).",
        ),
        _f(
            "redirect_uri",
            "Redirect URI (опц.)",
            type=FIELD_URL,
            help="Redirect URI для OAuth Meta.",
        ),
    ]
    steps = ["GET /{ig-user-id}?fields=id,username — токен и аккаунт валидны"]
    warnings = [
        "Аккаунт должен быть Professional (Business/Creator).",
        "Публикация требует публичного HTTPS image_url — локальный файл не подходит.",
        "Живые публикации выключены (только preview/dry-run).",
    ]
    return (
        fields,
        steps,
        warnings,
        "Нужен публичный HTTPS image_url (или будущий media-proxy Botfleet).",
    )


def _yandex_schema() -> tuple[list[ConnectionField], list[str], list[str], str]:
    fields = [
        _title_field(),
        _f(
            "url",
            "Публичная ссылка на папку",
            type=FIELD_URL,
            required=True,
            placeholder="https://disk.yandex.ru/d/...",
            help="Публичная ссылка на папку SMM.",
        ),
        _f("root_folder", "Root folder", placeholder="SMM", help="Корневая папка контента."),
        _tags_field(),
    ]
    steps = ["Публичная ссылка корректна и доступна", "Превью списка папки (без записи)"]
    warnings = ["Для Instagram нужен прямой публичный HTTPS image_url или media-proxy."]
    return (
        fields,
        steps,
        warnings,
        "Источник медиа: Telegram/VK скачивают файл; Instagram — нужен публичный URL.",
    )


def _website_schema() -> tuple[list[ConnectionField], list[str], list[str], str]:
    fields = [
        _title_field(),
        _f(
            "url",
            "URL сайта",
            type=FIELD_URL,
            required=True,
            placeholder="https://example.ru",
            help="Адрес витрины/лендинга.",
        ),
        _f("default_cta", "CTA по умолчанию", help="Призыв к действию для ссылок."),
    ]
    steps = ["Валидация URL (формат)", "Опциональная проверка доступности (HEAD/GET)"]
    warnings = ["Сайт используется для ссылок/SEO-CTA, сам по себе не публикует."]
    return (
        fields,
        steps,
        warnings,
        "Используется как источник ссылок/CTA, не как площадка публикации.",
    )


def _generic_schema(platform_key: str) -> tuple[list[ConnectionField], list[str], list[str], str]:
    """Схема для beta/planned-площадок: базовые поля, проверка = planned."""
    fields = [
        _title_field(),
        _f(
            "api_key",
            "Token / API key",
            type=FIELD_SECRET,
            secret=True,
            masked=True,
            help="Токен площадки (когда интеграция станет доступна).",
        ),
        _f("external_id", "ID аккаунта/канала", help="Идентификатор аккаунта на площадке."),
        _f("url", "URL (опц.)", type=FIELD_URL),
    ]
    steps = ["Интеграция в разработке — онлайн-проверка появится позже"]
    warnings = [
        "Интеграция в разработке: подключение сохраняется как черновик, публикация выключена."
    ]
    return fields, steps, warnings, ""


_BUILDERS = {
    "telegram": _telegram_schema,
    "vk": _vk_schema,
    "instagram": _instagram_schema,
    "yandex_disk": _yandex_schema,
    "website": _website_schema,
}


class PlatformConnectionSchemaService:
    """Отдаёт форму подключения по ключу платформы (на основе каталога)."""

    def get_connection_schema(self, platform_key: str) -> PlatformConnectionSchema:
        """Собрать схему формы подключения для платформы."""
        key = (platform_key or "").strip().lower()
        item = _CATALOG.get(key)
        builder = _BUILDERS.get(key)
        if builder is not None:
            fields, steps, warnings, media = builder()
        else:
            fields, steps, warnings, media = _generic_schema(key)
        title = item.title_ru if item is not None else key
        support = item.support_level if item is not None else "planned"
        live_supported = bool(item is not None and item.support_level == "active")
        description = item.notes_short if item is not None else "Подключение платформы."
        if item is not None and item.is_planned:
            # Planned/research: форма показывается, но проверка/публикация выключены.
            live_supported = False
        return PlatformConnectionSchema(
            platform_key=key,
            title=title,
            description=description,
            support_level=support,
            live_supported=live_supported,
            fields=fields,
            test_steps=steps,
            warnings=warnings,
            media_requirements=media,
            guide_anchor=item.guide_anchor if item is not None else key,
            help_url=f"/ui/guide/{key}",
        )


def get_platform_connection_schema_service() -> PlatformConnectionSchemaService:
    """DI-фабрика сервиса схем подключения."""
    return PlatformConnectionSchemaService()
