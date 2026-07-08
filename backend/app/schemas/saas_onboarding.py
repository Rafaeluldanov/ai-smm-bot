"""Pydantic-схемы SaaS-онбординга (личный кабинет).

Форма похожа на CRM «БОТ СММ», но для самостоятельной регистрации. Внутри сервис
маппит эти данные в CRM-пейлоад и переиспользует :class:`CrmBotSmmFormService`
(без дублирования бизнес-логики). Секрет ресурса (``api_key``) наружу не
возвращается; ``live_enabled`` принудительно false.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.crm_bot_smm import CrmPreviewResult


class SaasCompanyInput(BaseModel):
    """Раздел «Компания»."""

    company_name: str
    business_description: str = ""
    website_url: str | None = None
    has_website: bool = False
    manual_topics: list[str] = Field(default_factory=list)
    geography: list[str] = Field(default_factory=list)
    brand_tone: str = ""


class SaasProjectInput(BaseModel):
    """Раздел «Проект»."""

    project_slug: str
    project_name: str = ""
    promoted_resource_url: str | None = None
    default_site_url: str | None = None


class SaasKeywordInput(BaseModel):
    """Раздел «Ключевые слова» (один запрос)."""

    query: str
    frequency: int = 0
    cluster: str = ""
    product: str | None = None
    technology: str | None = None
    priority: int = 0
    intent: str = "commercial"


class SaasMediaSourceInput(BaseModel):
    """Раздел «Медиа-источники» (один источник)."""

    # yandex_disk | google_drive | manual | upload | website | other
    source_type: str
    title: str = ""
    url: str | None = None
    root_folder: str | None = None
    allowed_folders: list[str] = Field(default_factory=list)
    media_tags: list[str] = Field(default_factory=list)


class SaasPlatformInput(BaseModel):
    """Раздел «Платформы» (один ресурс публикации)."""

    # vk | telegram | instagram | youtube | rutube | other
    platform_type: str
    title: str = ""
    api_key: str | None = None
    external_id: str | None = None
    url: str | None = None
    live_enabled: bool = False
    tags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class SaasCategoryInput(BaseModel):
    """Раздел «Категории продвижения» (одна категория)."""

    title: str
    description: str = ""
    product_priorities: dict[str, int] = Field(default_factory=dict)
    technology_priorities: dict[str, int] = Field(default_factory=dict)
    media_tags: list[str] = Field(default_factory=list)
    keyword_queries: list[str] = Field(default_factory=list)
    resource_titles: list[str] = Field(default_factory=list)
    default_site_url: str | None = None
    cta: str = ""
    tone: str = ""


class SaasPlanInput(BaseModel):
    """Раздел «Расписание публикаций» (один план)."""

    category_title: str | None = None
    platforms: list[str] = Field(default_factory=list)
    weekdays: list[int] = Field(default_factory=list)
    posts_per_day: int = 1
    publish_times: list[str] = Field(default_factory=list)
    mode: str = "draft"
    timezone: str = "Europe/Moscow"
    start_date: str | None = None
    end_date: str | None = None


class SaasBillingInput(BaseModel):
    """Раздел «Биллинг»."""

    tariff_plan_slug: str | None = None
    starting_topup_amount: int | None = None
    accept_terms: bool = False


class SaasOnboardingPayload(BaseModel):
    """Полный SaaS-онбординг пейлоад."""

    model_config = ConfigDict(extra="ignore")

    company: SaasCompanyInput
    project: SaasProjectInput
    keywords: list[SaasKeywordInput] = Field(default_factory=list)
    media_sources: list[SaasMediaSourceInput] = Field(default_factory=list)
    platforms: list[SaasPlatformInput] = Field(default_factory=list)
    promotion_categories: list[SaasCategoryInput] = Field(default_factory=list)
    publishing_plans: list[SaasPlanInput] = Field(default_factory=list)
    billing: SaasBillingInput = Field(default_factory=SaasBillingInput)


class SaasOnboardingRequest(BaseModel):
    """Запрос preview/apply SaaS-онбординга под аккаунт."""

    account_id: int
    payload: SaasOnboardingPayload
    allow_live: bool = False


class SaasOnboardingResult(BaseModel):
    """Результат preview/apply (переиспользует CRM-превью + биллинг)."""

    account_id: int
    dry_run: bool
    project_id: int | None = None
    crm: CrmPreviewResult
    billing_balance_units: int | None = None
    warnings: list[str] = Field(default_factory=list)


class SaasRunRequest(BaseModel):
    """Запрос безопасного прогона проекта (dry/semi-auto)."""

    account_id: int
    category_id: int


class SaasBotRunResult(BaseModel):
    """Результат безопасного прогона проекта (dry/semi-auto) с биллингом."""

    account_id: int
    project_id: int
    category_id: int
    dry_run: bool
    estimated_units: int
    debited_units: int
    balance_units: int
    generated_posts: int = 0
    submitted_for_review: int = 0
    published_publications: int = 0
    warnings: list[str] = Field(default_factory=list)
    safety: list[str] = Field(default_factory=list)


class SaasProjectSummary(BaseModel):
    """Краткая карточка проекта в списке проектов аккаунта."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    website_url: str | None = None
    is_active: bool
    account_id: int | None = None


class DashboardRecentPost(BaseModel):
    """Недавний пост для дашборда."""

    id: int
    title: str | None = None
    status: str


class ProjectDashboard(BaseModel):
    """Дашборд проекта: конфигурация, контент, ревью, биллинг, рекомендации."""

    project_id: int
    project_slug: str
    project_name: str
    account_id: int | None = None
    website_url: str | None = None
    platforms_count: int = 0
    media_sources_count: int = 0
    categories_count: int = 0
    active_plans_count: int = 0
    recent_posts: list[DashboardRecentPost] = Field(default_factory=list)
    posts_needing_review: int = 0
    billing_balance_units: int | None = None
    next_recommended_actions: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
