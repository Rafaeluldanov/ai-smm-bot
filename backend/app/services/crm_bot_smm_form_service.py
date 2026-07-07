"""Сервис формы «БОТ СММ»: схема формы, валидация, apply и превью онбординга.

Отвечает за:
1. ``build_form_schema`` — JSON-схема формы для CRM (разделы и поля);
2. ``validate_onboarding_payload`` — доменная проверка пейлоада;
3. ``apply_onboarding_payload`` — dry-run превью или создание записей (без публикаций);
4. ``build_preview`` — превью по уже сохранённой конфигурации.

Безопасность: ни один режим не публикует посты и не включает live VK/TG;
``auto_publish`` и живые публикации запрещены на этом этапе.
"""

from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.repositories import crm_bot_smm_repository as repo
from app.repositories import project_repository
from app.schemas.crm_bot_smm import (
    BotSmmFormSchema,
    CrmBotProjectConfigCreate,
    CrmBotProjectConfigUpdate,
    CrmContentSourceCreate,
    CrmKeywordCreate,
    CrmOnboardingCategoryInput,
    CrmOnboardingPayload,
    CrmPreviewCategory,
    CrmPreviewPlan,
    CrmPreviewProject,
    CrmPreviewResource,
    CrmPreviewResult,
    CrmPromotionCategoryCreate,
    CrmPublishingPlanCreate,
    CrmSmmResourceCreate,
    CrmValidationResult,
    FormFieldSchema,
    FormSectionSchema,
)
from app.schemas.project import ProjectCreate, ProjectUpdate, normalize_slug

# Режимы плана публикаций, запрещённые/разрешённые на этом этапе.
_FORBIDDEN_PLAN_MODES = {"auto_publish"}
_ALLOWED_PLAN_MODES = {"draft", "semi_auto", "auto_schedule"}
_ALLOWED_PLATFORMS = {"telegram", "vk"}


class CrmOnboardingValidationError(Exception):
    """Онбординг-пейлоад не прошёл проверку (API → 422)."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors) if errors else "Ошибка валидации онбординга")


class CrmBotSmmFormService:
    """Схема формы, валидация и применение онбординга «БОТ СММ»."""

    # ------------------------------------------------------------------ #
    # 1. Схема формы                                                     #
    # ------------------------------------------------------------------ #

    def build_form_schema(self) -> BotSmmFormSchema:
        """Собрать JSON-схему формы «БОТ СММ» для отрисовки в CRM."""
        sections = [
            FormSectionSchema(
                key="project",
                title="Проект",
                description="Название и идентификаторы продвигаемого проекта.",
                fields=[
                    FormFieldSchema(
                        name="slug",
                        label="Код проекта (slug)",
                        type="text",
                        required=True,
                        help="Латиница, цифры, '-'/'_'. Например: teeon.",
                    ),
                    FormFieldSchema(name="name", label="Название", type="text"),
                    FormFieldSchema(
                        name="display_name", label="Отображаемое имя", type="text", required=True
                    ),
                    FormFieldSchema(name="crm_external_id", label="ID в CRM", type="text"),
                ],
            ),
            FormSectionSchema(
                key="site_or_topics",
                title="Сайт или тематика",
                description="Если сайта нет — задайте темы и сайты-референсы.",
                fields=[
                    FormFieldSchema(
                        name="has_website", label="Есть сайт", type="bool", default=False
                    ),
                    FormFieldSchema(
                        name="website_url",
                        label="Адрес сайта",
                        type="url",
                        required_if="has_website==true",
                        help="Обязателен, если есть сайт.",
                    ),
                    FormFieldSchema(
                        name="manual_topics",
                        label="Темы (если нет сайта)",
                        type="list",
                        required_if="has_website==false",
                    ),
                    FormFieldSchema(name="reference_sites", label="Сайты-референсы", type="list"),
                    FormFieldSchema(
                        name="business_description", label="Описание бизнеса", type="textarea"
                    ),
                    FormFieldSchema(name="geography", label="География", type="list"),
                    FormFieldSchema(name="brand_tone", label="Тон бренда", type="text"),
                    FormFieldSchema(
                        name="forbidden_phrases", label="Запрещённые фразы", type="list"
                    ),
                    FormFieldSchema(
                        name="required_review",
                        label="Обязательное ревью",
                        type="bool",
                        default=True,
                    ),
                ],
            ),
            FormSectionSchema(
                key="resources",
                title="Ресурсы продвижения",
                description="VK, Telegram, Яндекс Диск, сайт и другие ресурсы.",
                repeatable=True,
                min_items=1,
                fields=[
                    FormFieldSchema(
                        name="resource_type",
                        label="Тип ресурса",
                        type="select",
                        required=True,
                        options=["vk", "telegram", "yandex_disk", "website", "other"],
                    ),
                    FormFieldSchema(name="title", label="Название", type="text", required=True),
                    FormFieldSchema(
                        name="api_key",
                        label="Секрет/токен",
                        type="secret",
                        help="Хранится зашифрованно, наружу не возвращается.",
                    ),
                    FormFieldSchema(
                        name="external_id",
                        label="ID ресурса",
                        type="text",
                        help="Для VK — group_id. Обязателен external_id или url.",
                    ),
                    FormFieldSchema(name="url", label="Ссылка", type="url"),
                    FormFieldSchema(
                        name="yandex_public_url",
                        label="Публичная ссылка Яндекс Диска",
                        type="url",
                        help="Обязательна для yandex_disk.",
                    ),
                    FormFieldSchema(
                        name="yandex_root_folder", label="Корневая папка Диска", type="text"
                    ),
                    FormFieldSchema(name="tags", label="Теги", type="list"),
                    FormFieldSchema(name="keywords", label="Ключи ресурса", type="list"),
                    FormFieldSchema(
                        name="live_enabled",
                        label="Живая публикация",
                        type="bool",
                        default=False,
                        help="По умолчанию выключено. Живые публикации запрещены.",
                    ),
                ],
            ),
            FormSectionSchema(
                key="keywords",
                title="Ключевые слова",
                description="SEO-запросы для контент-плана.",
                repeatable=True,
                fields=[
                    FormFieldSchema(name="query", label="Запрос", type="text", required=True),
                    FormFieldSchema(
                        name="frequency", label="Частотность", type="number", default=0
                    ),
                    FormFieldSchema(name="cluster", label="Кластер", type="text"),
                    FormFieldSchema(name="product", label="Продукт", type="text"),
                    FormFieldSchema(name="technology", label="Технология", type="text"),
                    FormFieldSchema(
                        name="intent",
                        label="Интент",
                        type="select",
                        default="commercial",
                        options=["commercial", "informational", "brand", "process", "price"],
                    ),
                    FormFieldSchema(name="priority", label="Приоритет", type="number", default=0),
                ],
            ),
            FormSectionSchema(
                key="content_sources",
                title="Источники контента",
                description="Откуда брать медиа и материалы.",
                repeatable=True,
                fields=[
                    FormFieldSchema(
                        name="source_type",
                        label="Тип источника",
                        type="select",
                        required=True,
                        options=["yandex_disk", "website", "manual", "upload"],
                    ),
                    FormFieldSchema(name="title", label="Название", type="text", required=True),
                    FormFieldSchema(name="url", label="Ссылка", type="url"),
                    FormFieldSchema(name="root_folder", label="Корневая папка", type="text"),
                    FormFieldSchema(name="allowed_folders", label="Разрешённые папки", type="list"),
                    FormFieldSchema(name="media_tags", label="Медиа-теги", type="list"),
                ],
            ),
            FormSectionSchema(
                key="promotion_categories",
                title="Категории продвижения",
                description="Связка ключей, приоритетов и медиа-тегов.",
                repeatable=True,
                min_items=1,
                fields=[
                    FormFieldSchema(name="title", label="Название", type="text", required=True),
                    FormFieldSchema(name="description", label="Описание", type="textarea"),
                    FormFieldSchema(
                        name="resource_titles", label="Ресурсы (по названию)", type="list"
                    ),
                    FormFieldSchema(
                        name="keyword_queries", label="Ключи (по запросу)", type="list"
                    ),
                    FormFieldSchema(
                        name="product_priorities", label="Приоритеты продуктов", type="keyvalue"
                    ),
                    FormFieldSchema(
                        name="technology_priorities",
                        label="Приоритеты технологий",
                        type="keyvalue",
                    ),
                    FormFieldSchema(name="media_tags", label="Медиа-теги", type="list"),
                    FormFieldSchema(
                        name="default_site_url", label="Ссылка по умолчанию", type="url"
                    ),
                    FormFieldSchema(name="cta", label="Призыв к действию (CTA)", type="text"),
                    FormFieldSchema(name="tone", label="Тон", type="text"),
                    FormFieldSchema(
                        name="require_review", label="Обязательное ревью", type="bool", default=True
                    ),
                ],
            ),
            FormSectionSchema(
                key="publishing_plan",
                title="План публикаций",
                description="Расписание, платформы и режим. auto_publish запрещён.",
                repeatable=True,
                fields=[
                    FormFieldSchema(
                        name="category_title", label="Категория (по названию)", type="text"
                    ),
                    FormFieldSchema(
                        name="weekdays",
                        label="Дни недели",
                        type="multiselect",
                        options=["0", "1", "2", "3", "4", "5", "6"],
                        help="0=Пн … 6=Вс.",
                    ),
                    FormFieldSchema(
                        name="posts_per_day", label="Постов в день", type="number", default=1
                    ),
                    FormFieldSchema(
                        name="publish_times", label="Время публикаций (HH:MM)", type="list"
                    ),
                    FormFieldSchema(
                        name="platforms",
                        label="Платформы",
                        type="multiselect",
                        options=["telegram", "vk"],
                    ),
                    FormFieldSchema(
                        name="mode",
                        label="Режим",
                        type="select",
                        default="semi_auto",
                        options=["draft", "semi_auto", "auto_schedule"],
                        help="auto_publish недоступен (безопасность).",
                    ),
                    FormFieldSchema(name="start_date", label="Дата старта", type="date"),
                    FormFieldSchema(name="end_date", label="Дата окончания", type="date"),
                    FormFieldSchema(
                        name="timezone", label="Часовой пояс", type="text", default="Europe/Moscow"
                    ),
                ],
            ),
            FormSectionSchema(
                key="review_and_preview",
                title="Проверка и превью",
                description=(
                    "Валидация, превью и безопасный запуск. Публикации нет — "
                    "посты уходят на ревью (needs_review)."
                ),
                fields=[
                    FormFieldSchema(
                        name="dry_run",
                        label="Сухой прогон",
                        type="bool",
                        default=True,
                        help="dry-run ничего не пишет в БД.",
                    ),
                ],
            ),
        ]
        return BotSmmFormSchema(
            version="1.0",
            title="БОТ СММ — конфигуратор",
            sections=sections,
            disabled_modes=["auto_publish"],
            safety_notes=[
                "Живые публикации VK/Telegram выключены по умолчанию.",
                "auto_publish недоступен на этом этапе.",
                "Секрет ресурса не возвращается через API — только маска.",
                "Запуск возможен только через dry-run/semi_auto с ручным ревью.",
            ],
        )

    # ------------------------------------------------------------------ #
    # 2. Валидация                                                       #
    # ------------------------------------------------------------------ #

    def parse_payload(self, payload: dict[str, Any]) -> CrmOnboardingPayload:
        """Разобрать словарь в модель пейлоада (ValidationError пробрасывается)."""
        return CrmOnboardingPayload.model_validate(payload)

    def validate_onboarding_payload(self, payload: dict[str, Any]) -> CrmValidationResult:
        """Проверить онбординг-пейлоад и вернуть структурированный результат."""
        try:
            model = self.parse_payload(payload)
        except ValidationError as exc:
            errors = [self._format_pydantic_error(err) for err in exc.errors()]
            return CrmValidationResult(valid=False, errors=errors)
        return self._validate_model(model)

    def _validate_model(self, model: CrmOnboardingPayload) -> CrmValidationResult:
        errors: list[str] = []
        warnings: list[str] = []

        # Проект / slug.
        try:
            normalize_slug(model.project.slug)
        except ValueError as exc:
            errors.append(f"project.slug: {exc}")

        # Сайт или темы.
        site = model.site_or_topics
        if site.has_website and not (site.website_url or "").strip():
            errors.append("has_website=true, но website_url не задан")
        if not site.has_website and not site.manual_topics and not site.reference_sites:
            errors.append("has_website=false — нужны manual_topics или reference_sites")

        # Ресурсы.
        if not model.resources:
            errors.append("Нужен хотя бы один ресурс продвижения")
        for index, resource in enumerate(model.resources):
            label = f"resource[{index}] ({resource.resource_type})"
            if resource.resource_type == "vk" and not (resource.external_id or resource.url):
                errors.append(f"{label}: для vk нужен external_id или url")
            if resource.resource_type == "yandex_disk" and not resource.yandex_public_url:
                errors.append(f"{label}: для yandex_disk нужен yandex_public_url")
            if resource.live_enabled:
                errors.append(
                    f"{label}: live_enabled должен быть false (живые публикации запрещены)"
                )

        # Категории.
        if not model.promotion_categories:
            errors.append("Нужна хотя бы одна категория продвижения")
        for index, category in enumerate(model.promotion_categories):
            if not self._category_has_signal(category):
                errors.append(
                    f"category[{index}] '{category.title}': нужны ключи или "
                    "product/technology priorities"
                )

        # Планы публикаций.
        for index, plan in enumerate(model.publishing_plans):
            if plan.mode in _FORBIDDEN_PLAN_MODES:
                errors.append(
                    f"plan[{index}]: режим '{plan.mode}' запрещён (auto_publish недоступен)"
                )
            elif plan.mode not in _ALLOWED_PLAN_MODES:
                errors.append(f"plan[{index}]: неизвестный режим '{plan.mode}'")
            bad_platforms = [p for p in plan.platforms if p not in _ALLOWED_PLATFORMS]
            if bad_platforms:
                warnings.append(
                    f"plan[{index}]: неизвестные платформы {bad_platforms} — будут игнорированы"
                )
            if plan.category_title and plan.category_title not in {
                c.title for c in model.promotion_categories
            }:
                warnings.append(
                    f"plan[{index}]: категория '{plan.category_title}' не найдена среди категорий"
                )

        if not model.publishing_plans:
            warnings.append("План публикаций не задан — публикации не будут запланированы.")

        return CrmValidationResult(valid=not errors, errors=errors, warnings=warnings)

    @staticmethod
    def _category_has_signal(category: CrmOnboardingCategoryInput) -> bool:
        return bool(
            category.keyword_queries
            or category.product_priorities
            or category.technology_priorities
        )

    @staticmethod
    def _format_pydantic_error(err: Any) -> str:
        location = ".".join(str(part) for part in err.get("loc", ()))
        message = err.get("msg", "ошибка")
        return f"{location}: {message}" if location else message

    # ------------------------------------------------------------------ #
    # 3. Apply (dry-run / real)                                          #
    # ------------------------------------------------------------------ #

    def apply_onboarding_payload(
        self, db: Session, payload: dict[str, Any], dry_run: bool = True
    ) -> CrmPreviewResult:
        """Применить онбординг. dry_run=True — только превью, без записи в БД.

        Для невалидного пейлоада бросает :class:`CrmOnboardingValidationError`.
        Публикаций не выполняет ни в каком режиме.
        """
        try:
            model = self.parse_payload(payload)
        except ValidationError as exc:
            raise CrmOnboardingValidationError(
                [self._format_pydantic_error(err) for err in exc.errors()]
            ) from exc

        validation = self._validate_model(model)
        if not validation.valid:
            raise CrmOnboardingValidationError(validation.errors)

        if dry_run:
            return self._preview_from_payload(db, model, validation.warnings)
        return self._apply_real(db, model, validation.warnings)

    def _preview_from_payload(
        self, db: Session, model: CrmOnboardingPayload, warnings: list[str]
    ) -> CrmPreviewResult:
        existing = project_repository.get_project_by_slug(db, normalize_slug(model.project.slug))
        project = CrmPreviewProject(
            slug=normalize_slug(model.project.slug),
            name=model.project.name or model.project.display_name or model.project.slug,
            display_name=model.project.display_name or model.project.slug,
            has_website=model.site_or_topics.has_website,
            website_url=model.site_or_topics.website_url,
            exists=existing is not None,
        )
        resources = [
            CrmPreviewResource(
                title=res.title or res.resource_type,
                resource_type=res.resource_type,
                external_id=res.external_id,
                url=res.url,
                yandex_public_url=res.yandex_public_url,
                api_key_present=bool(res.api_key),
                live_enabled=False,
            )
            for res in model.resources
        ]
        categories = [
            CrmPreviewCategory(
                title=cat.title,
                keyword_count=len(cat.keyword_queries),
                product_priorities=cat.product_priorities,
                technology_priorities=cat.technology_priorities,
                default_site_url=cat.default_site_url,
            )
            for cat in model.promotion_categories
        ]
        plans = [
            CrmPreviewPlan(
                category_title=plan.category_title,
                mode=plan.mode,
                weekdays=plan.weekdays,
                posts_per_day=plan.posts_per_day,
                platforms=plan.platforms,
            )
            for plan in model.publishing_plans
        ]
        return CrmPreviewResult(
            dry_run=True,
            applied=False,
            config_id=None,
            project=project,
            resources=resources,
            keywords_count=len(model.keywords),
            content_sources_count=len(model.content_sources),
            categories=categories,
            plans=plans,
            warnings=[
                "dry_run=True: изменения в БД не сохранены (только превью).",
                *warnings,
            ],
            next_commands=[
                "Запустите apply с dry_run=false, чтобы создать проект и конфигурацию.",
                "После apply: make crm-category-plan category_id=<id> days=30",
            ],
        )

    def _apply_real(
        self, db: Session, model: CrmOnboardingPayload, warnings: list[str]
    ) -> CrmPreviewResult:
        slug = normalize_slug(model.project.slug)
        site = model.site_or_topics
        project_name = model.project.name or model.project.display_name or slug
        website_url = site.website_url if site.has_website else None

        # 1. Проект (создать или обновить сайт).
        project = project_repository.get_project_by_slug(db, slug)
        if project is None:
            project = project_repository.create_project(
                db,
                ProjectCreate(
                    name=project_name,
                    slug=slug,
                    description=site.business_description or None,
                    website_url=website_url,
                ),
            )
        elif website_url and project.website_url != website_url:
            project = project_repository.update_project(
                db, project, ProjectUpdate(website_url=website_url)
            )

        # 2. Конфигурация (создать или обновить).
        config_data = CrmBotProjectConfigCreate(
            project_id=project.id,
            display_name=model.project.display_name or project_name,
            crm_external_id=model.project.crm_external_id,
            website_url=website_url,
            has_website=site.has_website,
            manual_topics=site.manual_topics,
            reference_sites=site.reference_sites,
            business_description=site.business_description,
            geography=site.geography,
            brand_tone=site.brand_tone,
            forbidden_phrases=site.forbidden_phrases,
            required_review=site.required_review,
            status="active",
        )
        config = repo.get_config_by_project_id(db, project.id)
        if config is None:
            config = repo.create_config(db, config_data)
        else:
            config = repo.update_config(
                db,
                config,
                CrmBotProjectConfigUpdate(**config_data.model_dump(exclude={"project_id"})),
            )

        # 3. Ресурсы (live_enabled принудительно false).
        resource_id_by_title: dict[str, int] = {}
        for res in model.resources:
            created = repo.create_resource(
                db,
                CrmSmmResourceCreate(
                    project_id=project.id,
                    config_id=config.id,
                    resource_type=res.resource_type,
                    title=res.title or res.resource_type,
                    api_key=res.api_key,
                    external_id=res.external_id,
                    url=res.url,
                    yandex_public_url=res.yandex_public_url,
                    yandex_root_folder=res.yandex_root_folder,
                    tags=res.tags,
                    keywords=res.keywords,
                    live_enabled=False,
                    is_active=True,
                ),
            )
            resource_id_by_title.setdefault(created.title, created.id)

        # 4. Ключи.
        keyword_id_by_query: dict[str, int] = {}
        for kw in model.keywords:
            created_kw = repo.create_keyword(
                db,
                CrmKeywordCreate(
                    project_id=project.id,
                    config_id=config.id,
                    query=kw.query,
                    frequency=kw.frequency,
                    cluster=kw.cluster,
                    product=kw.product,
                    technology=kw.technology,
                    intent=kw.intent,
                    priority=kw.priority,
                ),
            )
            keyword_id_by_query.setdefault(kw.query, created_kw.id)

        # 5. Источники контента.
        for source in model.content_sources:
            repo.create_content_source(
                db,
                CrmContentSourceCreate(
                    project_id=project.id,
                    config_id=config.id,
                    source_type=source.source_type,
                    title=source.title or source.source_type,
                    url=source.url,
                    root_folder=source.root_folder,
                    allowed_folders=source.allowed_folders,
                    media_tags=source.media_tags,
                ),
            )

        # 6. Категории (связать ключи/ресурсы по значениям).
        category_id_by_title: dict[str, int] = {}
        for cat in model.promotion_categories:
            keyword_ids = [
                keyword_id_by_query[q] for q in cat.keyword_queries if q in keyword_id_by_query
            ]
            resource_ids = [
                resource_id_by_title[t] for t in cat.resource_titles if t in resource_id_by_title
            ]
            created_cat = repo.create_category(
                db,
                CrmPromotionCategoryCreate(
                    project_id=project.id,
                    config_id=config.id,
                    title=cat.title,
                    description=cat.description,
                    resource_ids=resource_ids,
                    keyword_ids=keyword_ids,
                    product_priorities=cat.product_priorities,
                    technology_priorities=cat.technology_priorities,
                    media_tags=cat.media_tags,
                    default_site_url=cat.default_site_url or website_url,
                    cta=cat.cta,
                    tone=cat.tone,
                    require_review=cat.require_review,
                    status="active",
                ),
            )
            category_id_by_title.setdefault(cat.title, created_cat.id)

        # 7. Планы публикаций (auto_publish уже отсеян валидацией).
        for plan in model.publishing_plans:
            category_id = category_id_by_title.get(plan.category_title or "")
            if category_id is None and category_id_by_title:
                category_id = next(iter(category_id_by_title.values()))
            if category_id is None:
                continue
            platforms = [p for p in plan.platforms if p in _ALLOWED_PLATFORMS]
            repo.create_plan(
                db,
                CrmPublishingPlanCreate(
                    project_id=project.id,
                    config_id=config.id,
                    category_id=category_id,
                    weekdays=plan.weekdays,
                    posts_per_day=plan.posts_per_day,
                    publish_times=plan.publish_times,
                    platforms=platforms,
                    mode=plan.mode,
                    start_date=plan.start_date,
                    end_date=plan.end_date,
                    timezone=plan.timezone,
                ),
            )

        preview = self.build_preview(db, config.id)
        preview.warnings = [
            "apply выполнен: записи созданы. Публикации НЕ выполнялись.",
            *warnings,
            *preview.warnings,
        ]
        return preview

    # ------------------------------------------------------------------ #
    # 4. Превью по сохранённой конфигурации                              #
    # ------------------------------------------------------------------ #

    def build_preview(self, db: Session, config_id: int) -> CrmPreviewResult:
        """Собрать превью по уже сохранённой конфигурации (config_id)."""
        config = repo.get_config_by_id(db, config_id)
        if config is None:
            raise CrmOnboardingValidationError([f"Конфигурация id={config_id} не найдена"])
        project = project_repository.get_project_by_id(db, config.project_id)
        slug = project.slug if project is not None else ""

        resources = repo.list_resources_by_config(db, config.id)
        keywords = repo.list_keywords_by_config(db, config.id)
        content_sources = repo.list_content_sources_by_config(db, config.id)
        categories = repo.list_categories_by_config(db, config.id)

        preview_project = CrmPreviewProject(
            slug=slug,
            name=project.name if project is not None else config.display_name,
            display_name=config.display_name,
            has_website=config.has_website,
            website_url=config.website_url,
            exists=project is not None,
        )
        preview_resources = [
            CrmPreviewResource(
                title=res.title,
                resource_type=res.resource_type,
                external_id=res.external_id,
                url=res.url,
                yandex_public_url=res.yandex_public_url,
                api_key_present=bool(res.api_key_encrypted),
                live_enabled=res.live_enabled,
            )
            for res in resources
        ]
        preview_categories = [
            CrmPreviewCategory(
                title=cat.title,
                keyword_count=len(cat.keyword_ids or []),
                product_priorities=dict(cat.product_priorities or {}),
                technology_priorities=dict(cat.technology_priorities or {}),
                default_site_url=cat.default_site_url,
            )
            for cat in categories
        ]

        preview_plans: list[CrmPreviewPlan] = []
        next_commands: list[str] = []
        for cat in categories:
            for plan in repo.list_plans_by_category(db, cat.id):
                preview_plans.append(
                    CrmPreviewPlan(
                        category_title=cat.title,
                        mode=plan.mode,
                        weekdays=list(plan.weekdays or []),
                        posts_per_day=plan.posts_per_day,
                        platforms=list(plan.platforms or []),
                    )
                )
            next_commands.append(f"make crm-category-plan category_id={cat.id} days=30")
            next_commands.append(
                f"POST /crm/bot-smm/categories/{cat.id}/run-dry (безопасно, без постов)"
            )
            next_commands.append(
                f"POST /crm/bot-smm/categories/{cat.id}/run-semi-auto (посты → needs_review)"
            )

        return CrmPreviewResult(
            dry_run=False,
            applied=True,
            config_id=config.id,
            project=preview_project,
            resources=preview_resources,
            keywords_count=len(keywords),
            content_sources_count=len(content_sources),
            categories=preview_categories,
            plans=preview_plans,
            warnings=["Живые публикации выключены. Секреты ресурсов не показываются."],
            next_commands=next_commands,
        )
