"""SEO-заполнение VK-группы: превью описания, статуса, закрепа, услуг, меню.

Готовит SEO-наполнение сообщества (Задачи 4–5) ДЕТЕРМИНИРОВАННО и БЕЗОПАСНО:
никаких вызовов VK API, ни в preview, ни в apply. Реальные изменения оформления
группы на этом этапе НЕ выполняются — только предпросмотр и план действий.

Гейты безопасности:
- ``VK_GROUP_SETUP_LIVE_ENABLED`` (по умолчанию false) — без него apply с
  ``dry_run=False`` блокируется;
- ``VK_GROUP_SETUP_ALLOWED_PROJECTS`` — список разрешённых проектов;
- даже при включённом флаге реальное оформление на этом этапе не отправляется.
"""

from app.config import Settings, get_settings
from app.schemas.seo import (
    VkGroupApplyAction,
    VkGroupApplyResult,
    VkGroupMenuItem,
    VkGroupSeoPreview,
    VkGroupServiceItem,
)
from app.services.seo_content_sources import (
    ProjectSeoProfile,
    get_project_seo_profile,
    rubric_title,
)

# SEO-хэштеги VK-группы по проектам (Задача 5.5). Порядок стабилен.
_SEO_HASHTAGS: dict[str, tuple[str, ...]] = {
    "teeon": (
        "#мерч",
        "#корпоративныймерч",
        "#промоодежда",
        "#футболкислоготипом",
        "#худислоготипом",
        "#пошивфутболок",
        "#пошивхуди",
        "#DTFпечать",
        "#вышивка",
        "#гравировка",
        "#УФпечать",
        "#шелкография",
        "#корпоративнаяодежда",
        "#пошивмерча",
        "#мерчмосква",
        "#производствомерча",
        "#TEEON",
    ),
    "fabric-souvenirs": (
        "#сувениры",
        "#корпоративныеподарки",
        "#брендирование",
        "#УФпечать",
        "#шелкография",
        "#тампопечать",
        "#гравировка",
        "#фабрикасувениров",
    ),
}

# Название и статус группы по проектам.
_GROUP_NAMES: dict[str, str] = {
    "teeon": "TEEON — корпоративный мерч и промо-одежда на заказ",
    "fabric-souvenirs": "Фабрика сувениров — корпоративные подарки и брендирование",
}

_GROUP_STATUSES: dict[str, str] = {
    "teeon": "Корпоративный мерч и промо-одежда на заказ | Пошив и нанесение логотипа",
    "fabric-souvenirs": "Сувенирная продукция и корпоративные подарки | Брендирование под заказ",
}


class VkGroupSetupNotAllowedError(Exception):
    """SEO-заполнение группы не разрешено для проекта (API → 403)."""

    def __init__(self, project_slug: str, reason: str) -> None:
        self.project_slug = project_slug
        self.reason = reason
        super().__init__(reason)


class VkGroupSetupLiveDisabledError(VkGroupSetupNotAllowedError):
    """Живое применение запрошено, но VK_GROUP_SETUP_LIVE_ENABLED=false."""

    def __init__(self, project_slug: str) -> None:
        super().__init__(
            project_slug,
            "Живое SEO-заполнение VK-группы отключено (VK_GROUP_SETUP_LIVE_ENABLED=false) — "
            "доступен только preview/dry-run",
        )


class VkGroupSetupProjectNotAllowedError(VkGroupSetupNotAllowedError):
    """Проект не входит в VK_GROUP_SETUP_ALLOWED_PROJECTS."""

    def __init__(self, project_slug: str) -> None:
        super().__init__(
            project_slug,
            f"Проект '{project_slug}' не входит в список VK_GROUP_SETUP_ALLOWED_PROJECTS",
        )


def build_vk_group_seo_profile(project_slug: str) -> ProjectSeoProfile:
    """Вернуть SEO-профиль проекта — источник данных для оформления группы."""
    return get_project_seo_profile(project_slug)


def build_vk_group_name(project_slug: str) -> str:
    """Название группы (SEO-ориентированное)."""
    profile = get_project_seo_profile(project_slug)
    return _GROUP_NAMES.get(project_slug, profile.brand_name)


def build_vk_short_description(project_slug: str) -> str:
    """Короткое описание группы (Задача 5.1)."""
    return get_project_seo_profile(project_slug).short_description


def _products_text(profile: ProjectSeoProfile) -> str:
    return ", ".join(profile.catalog_products)


def _technologies_text(profile: ProjectSeoProfile) -> str:
    return ", ".join(name for name, _ in profile.content_vector.priority_technologies)


def build_vk_group_description(project_slug: str) -> str:
    """Полное описание группы (Задача 5.2): производство, изделия, нанесение, B2B, CTA."""
    profile = get_project_seo_profile(project_slug)
    contacts = profile.contacts
    contacts_line = ", ".join(
        part for part in (contacts.phone, contacts.email, contacts.website) if part
    )
    lines = [
        f"{profile.brand_name} — производство корпоративной одежды и промо-мерча на заказ.",
        f"Что производим: {_products_text(profile)}.",
        f"Нанесение логотипа: {_technologies_text(profile)}.",
        "Собственное производство в Москве, полный цикл — от макета до готовой партии.",
        "Работаем с юрлицами: договор, отчётные документы, соблюдение сроков (B2B).",
        "Доставка по России.",
        (
            "Как заказать: напишите в сообщения группы или оставьте заявку на сайте — "
            "подберём изделие и нанесение, рассчитаем тираж, стоимость и сроки."
        ),
        f"Контакты: {contacts_line}.",
    ]
    return "\n".join(lines)


def build_vk_group_status(project_slug: str) -> str:
    """Статус группы (Задача 5.3)."""
    profile = get_project_seo_profile(project_slug)
    return _GROUP_STATUSES.get(project_slug, profile.short_description[:139])


def build_vk_pinned_post(project_slug: str) -> str:
    """Большой продающий закреплённый пост (Задача 5.4)."""
    profile = get_project_seo_profile(project_slug)
    parts = [
        f"{profile.brand_name} — производство корпоративного мерча и промо-одежды на заказ.",
        f"Что производим: {_products_text(profile)} — с нанесением логотипа.",
        f"Технологии нанесения: {_technologies_text(profile)}.",
        (
            "Кому подходит: компаниям, брендам, event- и HR-командам — мерч для сотрудников, "
            "промо-акций и подарков клиентам."
        ),
    ]
    if profile.trust_facts:
        parts.append("Почему мы: " + " ".join(profile.trust_facts))
    parts.append(
        "Как заказать: напишите в сообщения группы или оставьте заявку на сайте — "
        "рассчитаем тираж, стоимость и сроки."
    )
    if profile.site_url:
        parts.append(f"Подробнее и расчёт: {profile.site_url}")
    parts.append("Напишите нам — подберём изделие, нанесение и рассчитаем тираж.")
    return "\n\n".join(parts)


def build_vk_services_catalog(project_slug: str) -> list[VkGroupServiceItem]:
    """Список услуг для блока «Услуги» (изделия + технологии нанесения)."""
    profile = get_project_seo_profile(project_slug)
    services: list[VkGroupServiceItem] = []
    for page in profile.catalog_pages:
        services.append(
            VkGroupServiceItem(
                title=page.title,
                description=f"Пошив на заказ: {page.title.lower()} с нанесением логотипа.",
                url=page.url,
            )
        )
    for page in profile.branding_pages:
        services.append(
            VkGroupServiceItem(
                title=page.title,
                description=f"Нанесение логотипа: {page.title.lower()}.",
                url=page.url,
            )
        )
    return services


def build_vk_content_rubrics(project_slug: str) -> list[str]:
    """Рубрики контента группы (из контент-микса)."""
    profile = get_project_seo_profile(project_slug)
    return [rubric_title(label) for label, _ in profile.content_vector.content_mix]


def build_vk_seo_hashtags(project_slug: str) -> list[str]:
    """SEO-хэштеги группы (Задача 5.5)."""
    hashtags = _SEO_HASHTAGS.get(project_slug)
    if hashtags is not None:
        return list(hashtags)
    # Фолбэк для проектов без явного набора — из бренда и приоритетов.
    profile = get_project_seo_profile(project_slug)
    tags = [f"#{profile.brand_name.replace(' ', '').lower()}"]
    for name, _ in profile.content_vector.priority_products[:5]:
        tags.append("#" + name.replace(" ", "").replace("/", "").lower())
    return tags


def build_vk_menu_structure(project_slug: str) -> list[VkGroupMenuItem]:
    """Структура меню/навигации группы (ключевые страницы сайта)."""
    profile = get_project_seo_profile(project_slug)
    by_slug = {page.slug: page for page in profile.other_pages}
    order = ("catalog", "branding", "korporativnyy-merch", "portfolio", "faq", "contacts")
    menu: list[VkGroupMenuItem] = []
    for slug in order:
        page = by_slug.get(slug)
        if page is not None and page.url:
            menu.append(VkGroupMenuItem(title=page.title, url=page.url))
    return menu


def build_vk_group_links(project_slug: str) -> list[str]:
    """Ключевые ссылки на сайт для блока ссылок группы (без дублей)."""
    profile = get_project_seo_profile(project_slug)
    links: list[str] = []
    if profile.site_url:
        links.append(profile.site_url)
    for page in (*profile.other_pages, *profile.catalog_pages, *profile.branding_pages):
        if page.url and page.url not in links:
            links.append(page.url)
    return links[:12]


def preview_vk_group_setup(project_slug: str) -> VkGroupSeoPreview:
    """Собрать полное превью SEO-заполнения группы БЕЗ обращения к VK API."""
    profile = get_project_seo_profile(project_slug)
    warnings: list[str] = [
        "Реальные изменения VK-группы выключены — это предпросмотр (preview).",
        "Медиа брать из MediaAsset/Яндекс Диска по тегам; не выдавать внешние фото за свои кейсы.",
    ]
    if not profile.site_url:
        warnings.append("У проекта не задан сайт — ссылки недоступны (плейсхолдер второй группы).")
    if not profile.vk_group_id:
        warnings.append("VK group_id не задан для проекта (плейсхолдер второй группы).")

    return VkGroupSeoPreview(
        project_slug=project_slug,
        group_name=build_vk_group_name(project_slug),
        short_description=build_vk_short_description(project_slug),
        full_description=build_vk_group_description(project_slug),
        status=build_vk_group_status(project_slug),
        pinned_post=build_vk_pinned_post(project_slug),
        services=build_vk_services_catalog(project_slug),
        hashtags=build_vk_seo_hashtags(project_slug),
        links=build_vk_group_links(project_slug),
        rubrics=build_vk_content_rubrics(project_slug),
        menu=build_vk_menu_structure(project_slug),
        warnings=warnings,
    )


def _build_actions(preview: VkGroupSeoPreview) -> list[VkGroupApplyAction]:
    """План действий по оформлению группы (что было бы установлено)."""

    def _clip(value: str) -> str:
        collapsed = " ".join(value.split())
        return collapsed if len(collapsed) <= 120 else collapsed[:117] + "…"

    return [
        VkGroupApplyAction(
            action="set_name", target="group.title", value_preview=_clip(preview.group_name)
        ),
        VkGroupApplyAction(
            action="set_description",
            target="group.description",
            value_preview=_clip(preview.full_description),
        ),
        VkGroupApplyAction(
            action="set_status", target="group.status", value_preview=_clip(preview.status)
        ),
        VkGroupApplyAction(
            action="set_pinned_post", target="wall.pinned", value_preview=_clip(preview.pinned_post)
        ),
        VkGroupApplyAction(
            action="set_menu",
            target="group.menu",
            value_preview=_clip(", ".join(item.title for item in preview.menu)),
        ),
    ]


def apply_vk_group_setup(
    project_slug: str, dry_run: bool = True, settings: Settings | None = None
) -> VkGroupApplyResult:
    """Применить SEO-заполнение группы. По умолчанию dry_run=True (без изменений).

    Даже при ``dry_run=False`` и включённом флаге реальные изменения VK на этом
    этапе НЕ отправляются (safety). Без флага/разрешения проекта живое применение
    блокируется исключением.
    """
    settings = settings or get_settings()
    preview = preview_vk_group_setup(project_slug)
    actions = _build_actions(preview)
    live_enabled = settings.vk_group_setup_live_enabled
    allowed = project_slug in settings.vk_group_setup_allowed_projects_list
    warnings = list(preview.warnings)

    if dry_run:
        warnings.insert(0, "dry_run=True: реальных изменений в VK не выполнено (только план).")
        return VkGroupApplyResult(
            project_slug=project_slug,
            dry_run=True,
            live_enabled=live_enabled,
            applied=False,
            actions=actions,
            warnings=warnings,
            preview=preview,
        )

    if not live_enabled:
        raise VkGroupSetupLiveDisabledError(project_slug)
    if not allowed:
        raise VkGroupSetupProjectNotAllowedError(project_slug)

    # Флаг включён и проект разрешён, но реальное оформление на этом этапе не
    # выполняется — сохраняем безопасность (VK live остаётся выключенным).
    warnings.insert(
        0,
        "Живое оформление VK-группы на этом этапе не реализовано (safety) — "
        "изменения не отправлены.",
    )
    return VkGroupApplyResult(
        project_slug=project_slug,
        dry_run=False,
        live_enabled=live_enabled,
        applied=False,
        actions=actions,
        warnings=warnings,
        preview=preview,
    )
