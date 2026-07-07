"""REST API SEO-модуля: профиль, превью VK-группы, контент-план, apply.

Эндпоинты профиля/превью/плана детерминированы и не требуют БД (работают, даже
когда PostgreSQL остановлен). ``vk-group-apply`` по умолчанию dry_run=True и
блокируется без ``VK_GROUP_SETUP_LIVE_ENABLED=true``; реальные изменения VK на
этом этапе не выполняются.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.seo import (
    SeoContactsRead,
    SeoContentPlan,
    SeoContentVectorRead,
    SeoProjectProfileRead,
    SeoSitePageRead,
    VkGroupApplyRequest,
    VkGroupApplyResult,
    VkGroupSeoPreview,
)
from app.services.seo_content_plan_service import SeoContentPlanService
from app.services.seo_content_sources import (
    ProjectSeoProfile,
    SitePage,
    UnknownSeoProjectError,
    get_project_seo_profile,
)
from app.services.vk_group_seo_setup_service import (
    VkGroupSetupNotAllowedError,
    apply_vk_group_setup,
    preview_vk_group_setup,
)

router = APIRouter(prefix="/seo", tags=["seo"])


def _page_read(page: SitePage) -> SeoSitePageRead:
    return SeoSitePageRead(
        slug=page.slug,
        title=page.title,
        url=page.url,
        page_type=page.page_type,
        products=list(page.products),
        technologies=list(page.technologies),
        priority=page.priority,
    )


def _profile_read(profile: ProjectSeoProfile) -> SeoProjectProfileRead:
    vector = profile.content_vector
    contacts = profile.contacts
    return SeoProjectProfileRead(
        project_slug=profile.project_slug,
        brand_name=profile.brand_name,
        site_url=profile.site_url,
        vk_group_id=profile.vk_group_id,
        vk_screen_name=profile.vk_screen_name,
        contacts=SeoContactsRead(
            phone=contacts.phone,
            email=contacts.email,
            city=contacts.city,
            schedule=contacts.schedule,
            website=contacts.website,
        ),
        positioning=list(profile.positioning),
        trust_facts=list(profile.trust_facts),
        priority_products=list(profile.priority_products),
        priority_technologies=list(profile.priority_technologies),
        catalog_pages=[_page_read(page) for page in profile.catalog_pages],
        branding_pages=[_page_read(page) for page in profile.branding_pages],
        other_pages=[_page_read(page) for page in profile.other_pages],
        content_vector=SeoContentVectorRead(
            priority_products=dict(vector.priority_products),
            priority_technologies=dict(vector.priority_technologies),
            content_mix=dict(vector.content_mix),
            tone=list(vector.tone),
            forbidden=list(vector.forbidden),
        ),
        seo_queries_count=len(profile.seo_queries),
        seo_clusters=list(dict.fromkeys(query.cluster for query in profile.seo_queries)),
    )


def _get_profile_or_404(slug: str) -> ProjectSeoProfile:
    try:
        return get_project_seo_profile(slug)
    except UnknownSeoProjectError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/project/{slug}/profile", response_model=SeoProjectProfileRead)
def get_seo_profile(slug: str) -> SeoProjectProfileRead:
    """SEO-профиль проекта (контакты, сайт, каталог, нанесения, контент-вектор)."""
    return _profile_read(_get_profile_or_404(slug))


@router.get("/project/{slug}/vk-group-preview", response_model=VkGroupSeoPreview)
def get_vk_group_preview(slug: str) -> VkGroupSeoPreview:
    """Превью SEO-заполнения VK-группы. Реальные VK API вызовы не выполняются."""
    _get_profile_or_404(slug)
    return preview_vk_group_setup(slug)


@router.get("/project/{slug}/content-plan", response_model=SeoContentPlan)
def get_content_plan(
    slug: str,
    days: Annotated[int, Query(ge=1, le=180, description="Горизонт плана в днях")] = 30,
) -> SeoContentPlan:
    """SEO-контент-план проекта на N дней (оффлайн, без БД)."""
    _get_profile_or_404(slug)
    return SeoContentPlanService().build_plan(slug, days=days)


@router.post("/project/{slug}/vk-group-apply", response_model=VkGroupApplyResult)
def apply_vk_group(slug: str, payload: VkGroupApplyRequest | None = None) -> VkGroupApplyResult:
    """Применить SEO-заполнение VK-группы (dry_run=True по умолчанию).

    Живое применение (dry_run=False) блокируется без VK_GROUP_SETUP_LIVE_ENABLED
    и без разрешения проекта → 403. Даже при флаге реальные изменения VK на этом
    этапе не отправляются.
    """
    _get_profile_or_404(slug)
    request = payload or VkGroupApplyRequest()
    try:
        return apply_vk_group_setup(slug, dry_run=request.dry_run)
    except VkGroupSetupNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
