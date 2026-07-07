"""Pydantic-схемы SEO-модуля (профиль, контент-план, SEO-заполнение VK-группы).

Схемы служат представлением ответов API и результатов сервисов. Сами данные
собираются детерминированно из SEO-профиля проекта (без сети, AI и БД).
"""

from pydantic import BaseModel, Field


class SeoContactsRead(BaseModel):
    """Контакты проекта."""

    phone: str
    email: str
    city: str
    schedule: str
    website: str


class SeoSitePageRead(BaseModel):
    """Страница сайта проекта."""

    slug: str
    title: str
    url: str
    page_type: str
    products: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    priority: int = 0


class SeoQueryRead(BaseModel):
    """SEO-запрос seed-ядра."""

    query: str
    frequency: int
    cluster: str
    product: str | None = None
    technology: str | None = None
    intent: str
    priority: int


class SeoContentVectorRead(BaseModel):
    """Контентный вектор публикаций проекта."""

    priority_products: dict[str, int] = Field(default_factory=dict)
    priority_technologies: dict[str, int] = Field(default_factory=dict)
    content_mix: dict[str, int] = Field(default_factory=dict)
    tone: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)


class SeoProjectProfileRead(BaseModel):
    """SEO-профиль проекта (представление для API)."""

    project_slug: str
    brand_name: str
    site_url: str
    vk_group_id: str | None = None
    vk_screen_name: str | None = None
    contacts: SeoContactsRead
    positioning: list[str] = Field(default_factory=list)
    trust_facts: list[str] = Field(default_factory=list)
    priority_products: list[str] = Field(default_factory=list)
    priority_technologies: list[str] = Field(default_factory=list)
    catalog_pages: list[SeoSitePageRead] = Field(default_factory=list)
    branding_pages: list[SeoSitePageRead] = Field(default_factory=list)
    other_pages: list[SeoSitePageRead] = Field(default_factory=list)
    content_vector: SeoContentVectorRead
    seo_queries_count: int = 0
    seo_clusters: list[str] = Field(default_factory=list)


class SeoContentPlanItem(BaseModel):
    """Один день SEO-контент-плана."""

    day_number: int
    date: str
    weekday: str
    rubric: str
    topic: str
    seo_query: str
    seo_frequency: int
    product: str | None = None
    technology: str | None = None
    site_url: str
    site_page_title: str
    media_tag: str
    cta: str


class SeoContentPlan(BaseModel):
    """SEO-контент-план проекта на N дней."""

    project_slug: str
    brand_name: str
    site_url: str
    days: int
    start_date: str
    items: list[SeoContentPlanItem] = Field(default_factory=list)
    rubric_distribution: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class SeoMediaCandidate(BaseModel):
    """Кандидат-медиа под продукт/технологию (с учётом улучшенной копии)."""

    media_asset_id: int
    file_name: str
    source_type: str
    license_type: str | None = None
    status: str
    matched_tags: list[str] = Field(default_factory=list)
    media_source: str  # original | enhanced_variant
    preferred_media_path: str | None = None
    variant_id: int | None = None


class VkGroupServiceItem(BaseModel):
    """Услуга для блока «Услуги» VK-группы."""

    title: str
    description: str
    url: str


class VkGroupMenuItem(BaseModel):
    """Пункт меню/навигации VK-группы."""

    title: str
    url: str


class VkGroupSeoPreview(BaseModel):
    """Превью SEO-заполнения VK-группы (без реальных изменений)."""

    project_slug: str
    group_name: str
    short_description: str
    full_description: str
    status: str
    pinned_post: str
    services: list[VkGroupServiceItem] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    rubrics: list[str] = Field(default_factory=list)
    menu: list[VkGroupMenuItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class VkGroupApplyRequest(BaseModel):
    """Запрос на применение SEO-заполнения VK-группы."""

    dry_run: bool = True


class VkGroupApplyAction(BaseModel):
    """Одно планируемое действие по оформлению группы."""

    action: str
    target: str
    value_preview: str


class VkGroupApplyResult(BaseModel):
    """Результат apply: что было бы сделано (реальных изменений нет по умолчанию)."""

    project_slug: str
    dry_run: bool
    live_enabled: bool
    applied: bool
    actions: list[VkGroupApplyAction] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    preview: VkGroupSeoPreview
