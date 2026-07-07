"""Pydantic-схемы слоя «CRM Bot SMM Onboarding / Configurator».

Три группы схем:
1. Схема формы (``FormFieldSchema``/``FormSectionSchema``/``BotSmmFormSchema``) —
   JSON-описание формы «БОТ СММ», которое любая CRM отрисует во вкладке.
2. CRUD-схемы сущностей конфигурации (Create/Update/Read).
3. Схемы онбординг-пейлоада, результатов валидации, превью и запусков.

Безопасность: Read-схема ресурса НЕ содержит секрета — только ``api_key_present``
и ``api_key_masked``. Секрет (``api_key_encrypted``) наружу не отдаётся никогда.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- #
# 1. Схема формы для CRM                                                       #
# --------------------------------------------------------------------------- #


class FormFieldSchema(BaseModel):
    """Одно поле формы (как отрисовать инпут в CRM)."""

    name: str
    label: str
    # text | textarea | url | bool | number | select | multiselect | list |
    # keyvalue | time | date | secret
    type: str
    required: bool = False
    help: str = ""
    placeholder: str = ""
    default: Any = None
    options: list[str] = Field(default_factory=list)
    # Условная обязательность, напр. "has_website==true" (интерпретирует CRM/бекенд).
    required_if: str | None = None


class FormSectionSchema(BaseModel):
    """Раздел формы (группа полей)."""

    key: str
    title: str
    description: str = ""
    repeatable: bool = False
    min_items: int = 0
    fields: list[FormFieldSchema] = Field(default_factory=list)


class BotSmmFormSchema(BaseModel):
    """Полная JSON-схема формы «БОТ СММ» для CRM."""

    version: str
    title: str
    sections: list[FormSectionSchema] = Field(default_factory=list)
    disabled_modes: list[str] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 2. CRUD-схемы сущностей                                                      #
# --------------------------------------------------------------------------- #


class CrmBotProjectConfigCreate(BaseModel):
    """Создание конфигурации проекта."""

    project_id: int
    display_name: str
    crm_external_id: str | None = None
    website_url: str | None = None
    has_website: bool = False
    manual_topics: list[str] = Field(default_factory=list)
    reference_sites: list[str] = Field(default_factory=list)
    business_description: str = ""
    geography: list[str] = Field(default_factory=list)
    brand_tone: str = ""
    forbidden_phrases: list[str] = Field(default_factory=list)
    required_review: bool = True
    status: str = "draft"


class CrmBotProjectConfigUpdate(BaseModel):
    """Частичное обновление конфигурации проекта."""

    display_name: str | None = None
    crm_external_id: str | None = None
    website_url: str | None = None
    has_website: bool | None = None
    manual_topics: list[str] | None = None
    reference_sites: list[str] | None = None
    business_description: str | None = None
    geography: list[str] | None = None
    brand_tone: str | None = None
    forbidden_phrases: list[str] | None = None
    required_review: bool | None = None
    status: str | None = None


class CrmBotProjectConfigRead(BaseModel):
    """Конфигурация проекта в ответах API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    crm_external_id: str | None = None
    display_name: str
    website_url: str | None = None
    has_website: bool
    manual_topics: list[str] = Field(default_factory=list)
    reference_sites: list[str] = Field(default_factory=list)
    business_description: str = ""
    geography: list[str] = Field(default_factory=list)
    brand_tone: str = ""
    forbidden_phrases: list[str] = Field(default_factory=list)
    required_review: bool
    status: str
    created_at: datetime
    updated_at: datetime


class CrmSmmResourceCreate(BaseModel):
    """Создание ресурса продвижения.

    ``api_key`` — секрет в открытом виде (write-only). В БД он не сохраняется как
    есть: репозиторий кодирует его в ``api_key_encrypted`` и вычисляет маску.
    """

    project_id: int
    config_id: int
    resource_type: str
    title: str
    api_key: str | None = None
    external_id: str | None = None
    url: str | None = None
    yandex_public_url: str | None = None
    yandex_root_folder: str | None = None
    tags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    live_enabled: bool = False
    is_active: bool = True


class CrmSmmResourceUpdate(BaseModel):
    """Частичное обновление ресурса (``api_key`` — новый секрет, необязателен)."""

    resource_type: str | None = None
    title: str | None = None
    api_key: str | None = None
    external_id: str | None = None
    url: str | None = None
    yandex_public_url: str | None = None
    yandex_root_folder: str | None = None
    tags: list[str] | None = None
    keywords: list[str] | None = None
    live_enabled: bool | None = None
    is_active: bool | None = None


class CrmSmmResourceRead(BaseModel):
    """Ресурс в ответах API. Секрет не отдаётся — только факт и маска."""

    id: int
    project_id: int
    config_id: int
    resource_type: str
    title: str
    api_key_present: bool
    api_key_masked: str | None = None
    external_id: str | None = None
    url: str | None = None
    yandex_public_url: str | None = None
    yandex_root_folder: str | None = None
    tags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    live_enabled: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, obj: Any) -> "CrmSmmResourceRead":
        """Собрать Read из ORM-объекта, не пропуская секрет наружу."""
        return cls(
            id=obj.id,
            project_id=obj.project_id,
            config_id=obj.config_id,
            resource_type=obj.resource_type,
            title=obj.title,
            api_key_present=bool(obj.api_key_encrypted),
            api_key_masked=obj.api_key_masked,
            external_id=obj.external_id,
            url=obj.url,
            yandex_public_url=obj.yandex_public_url,
            yandex_root_folder=obj.yandex_root_folder,
            tags=list(obj.tags or []),
            keywords=list(obj.keywords or []),
            live_enabled=obj.live_enabled,
            is_active=obj.is_active,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )


class CrmKeywordCreate(BaseModel):
    """Создание ключевого запроса."""

    project_id: int
    config_id: int
    resource_id: int | None = None
    query: str
    frequency: int = 0
    cluster: str = ""
    product: str | None = None
    technology: str | None = None
    intent: str = "commercial"
    priority: int = 0
    is_active: bool = True


class CrmKeywordUpdate(BaseModel):
    """Частичное обновление ключевого запроса."""

    resource_id: int | None = None
    query: str | None = None
    frequency: int | None = None
    cluster: str | None = None
    product: str | None = None
    technology: str | None = None
    intent: str | None = None
    priority: int | None = None
    is_active: bool | None = None


class CrmKeywordRead(BaseModel):
    """Ключевой запрос в ответах API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    config_id: int
    resource_id: int | None = None
    query: str
    frequency: int
    cluster: str
    product: str | None = None
    technology: str | None = None
    intent: str
    priority: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CrmContentSourceCreate(BaseModel):
    """Создание источника контента."""

    project_id: int
    config_id: int
    source_type: str
    title: str
    url: str | None = None
    root_folder: str | None = None
    allowed_folders: list[str] = Field(default_factory=list)
    media_tags: list[str] = Field(default_factory=list)
    is_active: bool = True


class CrmContentSourceUpdate(BaseModel):
    """Частичное обновление источника контента."""

    source_type: str | None = None
    title: str | None = None
    url: str | None = None
    root_folder: str | None = None
    allowed_folders: list[str] | None = None
    media_tags: list[str] | None = None
    is_active: bool | None = None


class CrmContentSourceRead(BaseModel):
    """Источник контента в ответах API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    config_id: int
    source_type: str
    title: str
    url: str | None = None
    root_folder: str | None = None
    allowed_folders: list[str] = Field(default_factory=list)
    media_tags: list[str] = Field(default_factory=list)
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CrmPromotionCategoryCreate(BaseModel):
    """Создание категории продвижения."""

    project_id: int
    config_id: int
    title: str
    description: str = ""
    resource_ids: list[int] = Field(default_factory=list)
    keyword_ids: list[int] = Field(default_factory=list)
    product_priorities: dict[str, int] = Field(default_factory=dict)
    technology_priorities: dict[str, int] = Field(default_factory=dict)
    media_tags: list[str] = Field(default_factory=list)
    default_site_url: str | None = None
    cta: str = ""
    tone: str = ""
    require_review: bool = True
    status: str = "draft"


class CrmPromotionCategoryUpdate(BaseModel):
    """Частичное обновление категории продвижения."""

    title: str | None = None
    description: str | None = None
    resource_ids: list[int] | None = None
    keyword_ids: list[int] | None = None
    product_priorities: dict[str, int] | None = None
    technology_priorities: dict[str, int] | None = None
    media_tags: list[str] | None = None
    default_site_url: str | None = None
    cta: str | None = None
    tone: str | None = None
    require_review: bool | None = None
    status: str | None = None


class CrmPromotionCategoryRead(BaseModel):
    """Категория продвижения в ответах API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    config_id: int
    title: str
    description: str
    resource_ids: list[int] = Field(default_factory=list)
    keyword_ids: list[int] = Field(default_factory=list)
    product_priorities: dict[str, int] = Field(default_factory=dict)
    technology_priorities: dict[str, int] = Field(default_factory=dict)
    media_tags: list[str] = Field(default_factory=list)
    default_site_url: str | None = None
    cta: str
    tone: str
    require_review: bool
    status: str
    created_at: datetime
    updated_at: datetime


class CrmPublishingPlanCreate(BaseModel):
    """Создание плана публикаций категории."""

    project_id: int
    config_id: int
    category_id: int
    weekdays: list[int] = Field(default_factory=list)
    posts_per_day: int = 1
    publish_times: list[str] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    mode: str = "draft"
    start_date: str | None = None
    end_date: str | None = None
    timezone: str = "Europe/Moscow"
    is_active: bool = True


class CrmPublishingPlanUpdate(BaseModel):
    """Частичное обновление плана публикаций."""

    weekdays: list[int] | None = None
    posts_per_day: int | None = None
    publish_times: list[str] | None = None
    platforms: list[str] | None = None
    mode: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    timezone: str | None = None
    is_active: bool | None = None


class CrmPublishingPlanRead(BaseModel):
    """План публикаций в ответах API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    config_id: int
    category_id: int
    weekdays: list[int] = Field(default_factory=list)
    posts_per_day: int
    publish_times: list[str] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    mode: str
    start_date: str | None = None
    end_date: str | None = None
    timezone: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CrmOnboardingDraftCreate(BaseModel):
    """Создание черновика онбординга."""

    project_id: int | None = None
    step: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str = "draft"


class CrmOnboardingDraftUpdate(BaseModel):
    """Частичное обновление черновика онбординга."""

    project_id: int | None = None
    step: str | None = None
    payload: dict[str, Any] | None = None
    validation_errors: list[str] | None = None
    status: str | None = None


class CrmOnboardingDraftRead(BaseModel):
    """Черновик онбординга в ответах API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None = None
    step: str
    payload: dict[str, Any] = Field(default_factory=dict)
    validation_errors: list[str] = Field(default_factory=list)
    status: str
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
# 3. Онбординг-пейлоад, валидация, превью, запуски                             #
# --------------------------------------------------------------------------- #


class CrmOnboardingProjectInput(BaseModel):
    """Раздел «Проект» онбординг-пейлоада."""

    slug: str
    name: str | None = None
    display_name: str = ""
    crm_external_id: str | None = None


class CrmOnboardingSiteTopicsInput(BaseModel):
    """Раздел «Сайт или темы» онбординг-пейлоада."""

    has_website: bool = False
    website_url: str | None = None
    manual_topics: list[str] = Field(default_factory=list)
    reference_sites: list[str] = Field(default_factory=list)
    business_description: str = ""
    geography: list[str] = Field(default_factory=list)
    brand_tone: str = ""
    forbidden_phrases: list[str] = Field(default_factory=list)
    required_review: bool = True


class CrmOnboardingResourceInput(BaseModel):
    """Раздел «Ресурсы» онбординг-пейлоада (один ресурс)."""

    resource_type: str
    title: str = ""
    api_key: str | None = None
    external_id: str | None = None
    url: str | None = None
    yandex_public_url: str | None = None
    yandex_root_folder: str | None = None
    tags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    live_enabled: bool = False


class CrmOnboardingKeywordInput(BaseModel):
    """Раздел «Ключевые слова» онбординг-пейлоада (один запрос)."""

    query: str
    frequency: int = 0
    cluster: str = ""
    product: str | None = None
    technology: str | None = None
    intent: str = "commercial"
    priority: int = 0


class CrmOnboardingContentSourceInput(BaseModel):
    """Раздел «Источники контента» онбординг-пейлоада (один источник)."""

    source_type: str
    title: str = ""
    url: str | None = None
    root_folder: str | None = None
    allowed_folders: list[str] = Field(default_factory=list)
    media_tags: list[str] = Field(default_factory=list)


class CrmOnboardingCategoryInput(BaseModel):
    """Раздел «Категории продвижения» онбординг-пейлоада (одна категория).

    Ключи и ресурсы связываются по человекочитаемым значениям (query/title),
    поскольку числовые id появляются только после apply.
    """

    title: str
    description: str = ""
    resource_titles: list[str] = Field(default_factory=list)
    keyword_queries: list[str] = Field(default_factory=list)
    product_priorities: dict[str, int] = Field(default_factory=dict)
    technology_priorities: dict[str, int] = Field(default_factory=dict)
    media_tags: list[str] = Field(default_factory=list)
    default_site_url: str | None = None
    cta: str = ""
    tone: str = ""
    require_review: bool = True
    status: str = "draft"


class CrmOnboardingPlanInput(BaseModel):
    """Раздел «План публикаций» онбординг-пейлоада (один план)."""

    category_title: str | None = None
    weekdays: list[int] = Field(default_factory=list)
    posts_per_day: int = 1
    publish_times: list[str] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    mode: str = "draft"
    start_date: str | None = None
    end_date: str | None = None
    timezone: str = "Europe/Moscow"


class CrmOnboardingPayload(BaseModel):
    """Полный онбординг-пейлоад формы «БОТ СММ»."""

    model_config = ConfigDict(extra="ignore")

    project: CrmOnboardingProjectInput
    site_or_topics: CrmOnboardingSiteTopicsInput = Field(
        default_factory=CrmOnboardingSiteTopicsInput
    )
    resources: list[CrmOnboardingResourceInput] = Field(default_factory=list)
    keywords: list[CrmOnboardingKeywordInput] = Field(default_factory=list)
    content_sources: list[CrmOnboardingContentSourceInput] = Field(default_factory=list)
    promotion_categories: list[CrmOnboardingCategoryInput] = Field(default_factory=list)
    publishing_plans: list[CrmOnboardingPlanInput] = Field(default_factory=list)


class CrmValidationResult(BaseModel):
    """Результат валидации онбординг-пейлоада."""

    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CrmPreviewProject(BaseModel):
    """Проект в превью."""

    slug: str
    name: str
    display_name: str
    has_website: bool
    website_url: str | None = None
    exists: bool = False


class CrmPreviewResource(BaseModel):
    """Ресурс в превью (без секрета)."""

    title: str
    resource_type: str
    external_id: str | None = None
    url: str | None = None
    yandex_public_url: str | None = None
    api_key_present: bool = False
    live_enabled: bool = False


class CrmPreviewCategory(BaseModel):
    """Категория в превью."""

    title: str
    keyword_count: int = 0
    product_priorities: dict[str, int] = Field(default_factory=dict)
    technology_priorities: dict[str, int] = Field(default_factory=dict)
    default_site_url: str | None = None


class CrmPreviewPlan(BaseModel):
    """План публикаций в превью."""

    category_title: str | None = None
    mode: str
    weekdays: list[int] = Field(default_factory=list)
    posts_per_day: int = 1
    platforms: list[str] = Field(default_factory=list)


class CrmPreviewResult(BaseModel):
    """Превью/результат apply онбординга: что будет/было создано."""

    dry_run: bool
    applied: bool
    config_id: int | None = None
    project: CrmPreviewProject
    resources: list[CrmPreviewResource] = Field(default_factory=list)
    keywords_count: int = 0
    content_sources_count: int = 0
    categories: list[CrmPreviewCategory] = Field(default_factory=list)
    plans: list[CrmPreviewPlan] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    next_commands: list[str] = Field(default_factory=list)


class CrmConnectionTestRequest(BaseModel):
    """Запрос теста подключения ресурса (безопасный, без публикаций)."""

    test_connection: bool = False
    dry_run: bool = True


class CrmConnectionTestResult(BaseModel):
    """Результат теста подключения (сеть не вызывается; секрет не печатается)."""

    resource_id: int
    resource_type: str
    performed: bool
    ok: bool
    api_key_present: bool
    api_key_masked: str | None = None
    detail: str
    warnings: list[str] = Field(default_factory=list)


class CrmCategoryRunResult(BaseModel):
    """Результат прогона категории (dry-run / semi-auto). Публикаций нет."""

    category_id: int
    project_slug: str
    mode: str
    dry_run: bool
    run_id: int | None = None
    generated_posts: int = 0
    submitted_for_review: int = 0
    published_publications: int = 0
    posts_needing_media: int = 0
    warnings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    safety: list[str] = Field(default_factory=list)


class CrmCategoryRunPreview(BaseModel):
    """Превью прогона категории (что будет запущено, без записи в БД)."""

    category_id: int
    project_slug: str
    mode: str
    posts_per_week: int
    business_priorities: dict[str, int] = Field(default_factory=dict)
    platforms: list[str] = Field(default_factory=list)
    content_plan_days: int = 30
    site_url: str = ""
    safety: list[str] = Field(default_factory=list)
    next_commands: list[str] = Field(default_factory=list)
