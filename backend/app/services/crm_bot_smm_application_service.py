"""Интеграция конфигурации «БОТ СММ» с существующими SEO-модулями.

Строит SEO-профиль, контент-план и безопасный semi_auto-прогон из сохранённой
конфигурации CRM, переиспользуя:
- :mod:`app.services.seo_content_sources` — SEO-профили (preset TEEON / fabric);
- :mod:`app.services.site_link_selection_service` — выбор ссылки на сайт;
- :mod:`app.services.seo_content_plan_service` — резервный контент-план;
- :mod:`app.services.seo_media_selection_service` — подбор медиа (в превью);
- :mod:`app.services.autonomous_pipeline_service` — прогон pipeline.

Правила безопасности:
- проект TEEON/fabric — используется готовый SEO-профиль как preset;
- новый проект без сайта — временный SEO-профиль из тем/референсов;
- есть сайт — website_url становится главным источником ссылок;
- публикация только через semi_auto/dry-run; live-публикаций нет.
"""

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models.crm_bot_smm import CrmBotProjectConfig, CrmPromotionCategory
from app.models.project import Project
from app.repositories import crm_bot_smm_repository as repo
from app.repositories import project_repository
from app.schemas.autonomous import AutonomousModeSettings, AutonomousRunRequest
from app.schemas.crm_bot_smm import CrmCategoryRunPreview, CrmCategoryRunResult
from app.schemas.seo import SeoContentPlan, SeoContentPlanItem
from app.services.autonomous_pipeline_service import AutonomousPipelineService
from app.services.seo_content_plan_service import SeoContentPlanService
from app.services.seo_content_sources import (
    Contacts,
    ContentVector,
    ProjectSeoProfile,
    SeoQuery,
    SitePage,
    get_project_seo_profile,
    list_supported_seo_projects,
)
from app.services.site_link_selection_service import select_site_link

_WEEKDAYS_RU: tuple[str, ...] = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
_ALLOWED_PLATFORMS = ("telegram", "vk")
_DEFAULT_CONTENT_MIX: tuple[tuple[str, int], ...] = (
    ("товары/изделия", 40),
    ("технологии нанесения", 30),
    ("производство/процесс", 20),
    ("FAQ/как выбрать", 10),
)
_DEFAULT_CTA = "Заявка и расчёт — в сообщениях группы или на сайте."


class CrmCategoryNotFoundError(Exception):
    """Категория продвижения не найдена (API → 404)."""

    def __init__(self, category_id: int) -> None:
        self.category_id = category_id
        super().__init__(f"Категория продвижения id={category_id} не найдена")


class CrmConfigNotFoundError(Exception):
    """Конфигурация «БОТ СММ» не найдена (API → 404)."""

    def __init__(self, config_id: int) -> None:
        self.config_id = config_id
        super().__init__(f"Конфигурация id={config_id} не найдена")


class CrmBotSmmApplicationService:
    """Связывает конфигурацию CRM с SEO-модулями и автономным прогоном."""

    def __init__(
        self,
        pipeline_service: AutonomousPipelineService | None = None,
        content_plan_service: SeoContentPlanService | None = None,
    ) -> None:
        self._pipeline = pipeline_service
        self._content_plan = content_plan_service or SeoContentPlanService()

    def _get_pipeline(self) -> AutonomousPipelineService:
        """Ленивая сборка pipeline через deps (без циклического импорта)."""
        if self._pipeline is None:
            from app.api.deps import get_autonomous_pipeline_service

            self._pipeline = get_autonomous_pipeline_service()
        return self._pipeline

    # ------------------------------------------------------------------ #
    # Загрузка контекста                                                 #
    # ------------------------------------------------------------------ #

    def _load_config(self, db: Session, config_id: int) -> tuple[CrmBotProjectConfig, Project]:
        config = repo.get_config_by_id(db, config_id)
        if config is None:
            raise CrmConfigNotFoundError(config_id)
        project = project_repository.get_project_by_id(db, config.project_id)
        if project is None:
            raise CrmConfigNotFoundError(config_id)
        return config, project

    def _load_category(
        self, db: Session, category_id: int
    ) -> tuple[CrmPromotionCategory, CrmBotProjectConfig, Project]:
        category = repo.get_category_by_id(db, category_id)
        if category is None:
            raise CrmCategoryNotFoundError(category_id)
        config, project = self._load_config(db, category.config_id)
        return category, config, project

    @staticmethod
    def _is_preset(slug: str) -> bool:
        return slug in list_supported_seo_projects()

    # ------------------------------------------------------------------ #
    # SEO-профиль из конфигурации                                        #
    # ------------------------------------------------------------------ #

    def build_seo_profile_from_config(self, db: Session, config_id: int) -> ProjectSeoProfile:
        """Собрать SEO-профиль из конфигурации.

        Для TEEON/fabric — готовый preset. Для нового проекта — временный профиль
        из тем/референсов/ключей (site_url = website_url, если сайт задан).
        """
        config, project = self._load_config(db, config_id)
        if self._is_preset(project.slug):
            return get_project_seo_profile(project.slug)
        return self._build_temporary_profile(db, config, project)

    def _build_temporary_profile(
        self, db: Session, config: CrmBotProjectConfig, project: Project
    ) -> ProjectSeoProfile:
        keywords = repo.list_keywords_by_config(db, config.id)
        categories = repo.list_categories_by_config(db, config.id)

        seo_queries = tuple(
            SeoQuery(
                query=kw.query,
                frequency=kw.frequency,
                cluster=kw.cluster or "manual",
                product=kw.product,
                technology=kw.technology,
                intent=kw.intent,
                priority=kw.priority,
            )
            for kw in keywords
        )

        products: dict[str, int] = {}
        technologies: dict[str, int] = {}
        for cat in categories:
            for name, weight in (cat.product_priorities or {}).items():
                products[name] = max(products.get(name, 0), int(weight))
            for name, weight in (cat.technology_priorities or {}).items():
                technologies[name] = max(technologies.get(name, 0), int(weight))
        for kw in keywords:
            if kw.product:
                products.setdefault(kw.product, 50)
            if kw.technology:
                technologies.setdefault(kw.technology, 50)
        for topic in config.manual_topics or []:
            products.setdefault(str(topic), 40)

        site_url = config.website_url or ""
        other_pages: list[SitePage] = []
        if site_url:
            other_pages.append(
                SitePage(slug="home", title=config.display_name, url=site_url, page_type="home")
            )
        for index, ref in enumerate(config.reference_sites or []):
            other_pages.append(
                SitePage(
                    slug=f"reference-{index}",
                    title=f"Референс {index + 1}",
                    url=str(ref),
                    page_type="reference",
                )
            )

        content_vector = ContentVector(
            priority_products=tuple(sorted(products.items(), key=lambda x: -x[1])),
            priority_technologies=tuple(sorted(technologies.items(), key=lambda x: -x[1])),
            content_mix=_DEFAULT_CONTENT_MIX,
            tone=(config.brand_tone,) if config.brand_tone else ("экспертный", "без хайпа"),
            forbidden=tuple(config.forbidden_phrases or ()),
        )
        return ProjectSeoProfile(
            project_slug=project.slug,
            brand_name=config.display_name,
            site_url=site_url,
            contacts=Contacts(phone="", email="", city="", schedule="", website=site_url),
            catalog_pages=(),
            branding_pages=(),
            seo_queries=seo_queries,
            priority_products=tuple(products),
            priority_technologies=tuple(technologies),
            content_vector=content_vector,
            other_pages=tuple(other_pages),
            short_description=config.business_description,
            catalog_products=tuple(products),
        )

    # ------------------------------------------------------------------ #
    # Контент-план из категории                                          #
    # ------------------------------------------------------------------ #

    def build_content_plan_from_category(
        self, db: Session, category_id: int, days: int = 30
    ) -> SeoContentPlan:
        """Собрать контент-план категории на N дней (каждый день — со ссылкой)."""
        category, config, project = self._load_category(db, category_id)
        days = max(days, 1)
        slug = project.slug
        is_preset = self._is_preset(slug)

        preset_site = get_project_seo_profile(slug).site_url if is_preset else ""
        base_site = category.default_site_url or config.website_url or preset_site or ""

        subjects = self._category_subjects(db, category, config)
        if not subjects and is_preset:
            # Резервный путь: переиспользуем готовый сервис контент-плана.
            return self._content_plan.build_plan(slug, days=days)
        if not subjects:
            subjects = [{"query": category.title, "product": None, "technology": None}]

        warnings: list[str] = []
        if not base_site:
            warnings.append("У проекта не задан сайт — ссылки берутся из категории/пусты.")

        start = date.today()
        items: list[SeoContentPlanItem] = []
        for day_index in range(days):
            subject = subjects[day_index % len(subjects)]
            item = self._plan_item(
                day_index=day_index,
                start=start,
                subject=subject,
                slug=slug,
                is_preset=is_preset,
                base_site=base_site,
                category=category,
            )
            items.append(item)

        distribution: dict[str, int] = {}
        for item in items:
            distribution[item.rubric] = distribution.get(item.rubric, 0) + 1

        return SeoContentPlan(
            project_slug=slug,
            brand_name=config.display_name,
            site_url=base_site,
            days=days,
            start_date=start.isoformat(),
            items=items,
            rubric_distribution=distribution,
            warnings=warnings,
        )

    def _category_subjects(
        self, db: Session, category: CrmPromotionCategory, config: CrmBotProjectConfig
    ) -> list[dict[str, str | None]]:
        """Собрать предметы плана: ключи категории + приоритеты продуктов/технологий."""
        subjects: list[dict[str, str | None]] = []
        seen: set[str] = set()

        keyword_rows_raw = [repo.get_keyword_by_id(db, kid) for kid in (category.keyword_ids or [])]
        keyword_rows = [k for k in keyword_rows_raw if k is not None]
        if not keyword_rows:
            keyword_rows = repo.list_keywords_by_config(db, config.id)
        for kw in keyword_rows:
            if kw.query in seen:
                continue
            seen.add(kw.query)
            subjects.append({"query": kw.query, "product": kw.product, "technology": kw.technology})

        for name, _weight in sorted(
            (category.product_priorities or {}).items(), key=lambda x: -x[1]
        ):
            query = f"{name} на заказ"
            if query in seen:
                continue
            seen.add(query)
            subjects.append({"query": query, "product": name, "technology": None})

        for name, _weight in sorted(
            (category.technology_priorities or {}).items(), key=lambda x: -x[1]
        ):
            query = f"нанесение логотипа {name}"
            if query in seen:
                continue
            seen.add(query)
            subjects.append({"query": query, "product": None, "technology": name})

        return subjects

    def _plan_item(
        self,
        *,
        day_index: int,
        start: date,
        subject: dict[str, str | None],
        slug: str,
        is_preset: bool,
        base_site: str,
        category: CrmPromotionCategory,
    ) -> SeoContentPlanItem:
        current = start + timedelta(days=day_index)
        product = subject.get("product")
        technology = subject.get("technology")
        query = subject.get("query") or category.title

        site_url = base_site
        site_title = ""
        if is_preset:
            link = select_site_link(
                slug,
                seo_query=query,
                products=[product] if product else [],
                technologies=[technology] if technology else [],
            )
            if link is not None:
                site_url = link.url
                site_title = link.title

        media_tags = category.media_tags or []
        media_tag = technology or product or (media_tags[0] if media_tags else "мерч")

        if technology:
            topic = f"Нанесение логотипа: {technology}"
            rubric = "Технологии нанесения"
        elif product:
            topic = f"{_cap(product)} с логотипом на заказ"
            rubric = "Товары и изделия"
        else:
            topic = _cap(query)
            rubric = "Продвижение"

        return SeoContentPlanItem(
            day_number=day_index + 1,
            date=current.isoformat(),
            weekday=_WEEKDAYS_RU[current.weekday()],
            rubric=rubric,
            topic=topic,
            seo_query=query,
            seo_frequency=0,
            product=product,
            technology=technology,
            site_url=site_url,
            site_page_title=site_title,
            media_tag=str(media_tag),
            cta=category.cta or _DEFAULT_CTA,
        )

    # ------------------------------------------------------------------ #
    # Автономный прогон из категории                                     #
    # ------------------------------------------------------------------ #

    def build_autonomous_run_request_from_category(
        self, db: Session, category_id: int
    ) -> AutonomousRunRequest:
        """Построить безопасный semi_auto-запрос прогона по категории."""
        category, _config, project = self._load_category(db, category_id)
        plans = repo.list_plans_by_category(db, category_id)
        plan = plans[0] if plans else None

        posts_per_day = plan.posts_per_day if plan is not None else 1
        weekdays = list(plan.weekdays or []) if plan is not None else []
        posts_per_week = max(1, posts_per_day * (len(weekdays) or 1))

        platforms = [
            p for p in (list(plan.platforms) if plan is not None else []) if p in _ALLOWED_PLATFORMS
        ]
        if not platforms:
            platforms = list(_ALLOWED_PLATFORMS)

        business_priorities = self._business_priorities(db, category)

        return AutonomousRunRequest(
            project_id=project.id,
            mode="semi_auto",
            weeks=1,
            posts_per_week=posts_per_week,
            business_priorities=business_priorities or None,
            settings=AutonomousModeSettings(
                allow_external_images=True,
                allow_auto_approve=False,
                allow_auto_schedule=False,
                allow_auto_publish=False,
                require_human_review=True,
                platforms=platforms,
                dry_run=False,
            ),
        )

    def _business_priorities(self, db: Session, category: CrmPromotionCategory) -> dict[str, int]:
        priorities: dict[str, int] = {}
        for name, weight in (category.product_priorities or {}).items():
            priorities[name] = int(weight)
        for name, weight in (category.technology_priorities or {}).items():
            priorities.setdefault(name, int(weight))
        if not priorities:
            keyword_rows = [repo.get_keyword_by_id(db, kid) for kid in (category.keyword_ids or [])]
            for kw in keyword_rows:
                if kw is not None and kw.product:
                    priorities.setdefault(kw.product, 100)
        return priorities

    def preview_category_run(self, db: Session, category_id: int) -> CrmCategoryRunPreview:
        """Показать, что будет запущено, без записи в БД и без публикаций."""
        category, config, project = self._load_category(db, category_id)
        request = self.build_autonomous_run_request_from_category(db, category_id)
        preset_site = (
            get_project_seo_profile(project.slug).site_url if self._is_preset(project.slug) else ""
        )
        site_url = category.default_site_url or config.website_url or preset_site or ""
        return CrmCategoryRunPreview(
            category_id=category_id,
            project_slug=project.slug,
            mode="semi_auto",
            posts_per_week=request.posts_per_week,
            business_priorities=request.business_priorities or {},
            platforms=request.settings.platforms if request.settings else [],
            content_plan_days=30,
            site_url=site_url,
            safety=[
                "Публикации не выполняются: режим semi_auto.",
                "Посты уходят на ревью (needs_review).",
                "Живые публикации VK/Telegram выключены.",
            ],
            next_commands=[
                f"POST /crm/bot-smm/categories/{category_id}/run-dry",
                f"POST /crm/bot-smm/categories/{category_id}/run-semi-auto",
                f"make crm-category-plan category_id={category_id} days=30",
            ],
        )

    def run_category_semi_auto(
        self, db: Session, category_id: int, dry_run: bool = True
    ) -> CrmCategoryRunResult:
        """Запустить безопасный semi_auto-прогон категории.

        Не публикует и не включает live VK/TG. При dry_run=False создаёт посты и
        отправляет их на ревью (needs_review); при dry_run=True — только план.
        """
        category, _config, project = self._load_category(db, category_id)
        request = self.build_autonomous_run_request_from_category(db, category_id)
        settings = (request.settings or AutonomousModeSettings()).model_copy(
            update={"dry_run": dry_run, "allow_auto_publish": False, "allow_auto_schedule": False}
        )
        request = request.model_copy(update={"mode": "semi_auto", "settings": settings})

        result = self._get_pipeline().run_pipeline(db, request)

        return CrmCategoryRunResult(
            category_id=category_id,
            project_slug=project.slug,
            mode="semi_auto",
            dry_run=dry_run,
            run_id=result.run.id,
            generated_posts=result.generated_posts,
            submitted_for_review=result.submitted_for_review,
            published_publications=result.published_publications,
            posts_needing_media=result.posts_needing_media,
            warnings=list(result.warnings),
            next_actions=[
                "Согласуйте посты в /post-reviews (needs_review).",
                "Проверьте подбор медиа при необходимости досъёмки.",
            ],
            safety=[
                "Публикации НЕ выполнялись (semi_auto).",
                "Живые публикации VK/Telegram выключены.",
                f"Опубликовано публикаций: {result.published_publications} (ожидается 0).",
            ],
        )


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text
