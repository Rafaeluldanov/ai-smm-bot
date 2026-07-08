"""SaaS-онбординг: форма личного кабинета поверх CRM-конфигуратора.

Переиспользует :class:`CrmBotSmmFormService` (валидация + идемпотентный apply +
маскировка секретов + принудительный live_enabled=false), добавляя привязку
проекта к аккаунту и провижининг биллинга. Бизнес-логика онбординга НЕ дублируется.

Безопасность: секрет ресурса наружу не возвращается; live-публикации остаются
выключенными даже при ``allow_live`` (запрос лишь фиксируется предупреждением);
auto_publish запрещён CRM-валидацией.
"""

from typing import Any

from sqlalchemy.orm import Session

from app.models.project import Project
from app.repositories import (
    account_repository,
    billing_repository,
    post_repository,
    project_repository,
)
from app.repositories import (
    crm_bot_smm_repository as crm_repo,
)
from app.schemas.crm_bot_smm import BotSmmFormSchema, FormFieldSchema, FormSectionSchema
from app.schemas.project import normalize_slug
from app.schemas.saas_onboarding import (
    DashboardRecentPost,
    ProjectDashboard,
    SaasOnboardingPayload,
    SaasOnboardingResult,
)
from app.services.billing_service import BillingService
from app.services.crm_bot_smm_form_service import CrmBotSmmFormService


class SaasOnboardingError(Exception):
    """Ошибка SaaS-онбординга (аккаунт не найден, live без прав и т. п.)."""


class SaasOnboardingService:
    """Форма/preview/apply SaaS-онбординга и дашборд проекта."""

    def __init__(
        self,
        crm_form_service: CrmBotSmmFormService | None = None,
        billing_service: BillingService | None = None,
    ) -> None:
        self._crm = crm_form_service or CrmBotSmmFormService()
        self._billing = billing_service or BillingService()

    # ------------------------------------------------------------------ #
    # Форма                                                              #
    # ------------------------------------------------------------------ #

    def build_form_schema(self) -> BotSmmFormSchema:
        """JSON-схема SaaS-формы личного кабинета (разделы company..billing)."""
        sections = [
            FormSectionSchema(
                key="company",
                title="Компания",
                description="Название, описание и сайт (или темы, если сайта нет).",
                fields=[
                    FormFieldSchema(
                        name="company_name", label="Название компании", type="text", required=True
                    ),
                    FormFieldSchema(
                        name="business_description", label="Описание бизнеса", type="textarea"
                    ),
                    FormFieldSchema(
                        name="has_website", label="Есть сайт", type="bool", default=False
                    ),
                    FormFieldSchema(
                        name="website_url",
                        label="Адрес сайта",
                        type="url",
                        required_if="has_website==true",
                    ),
                    FormFieldSchema(
                        name="manual_topics",
                        label="Темы (если нет сайта)",
                        type="list",
                        required_if="has_website==false",
                    ),
                    FormFieldSchema(name="geography", label="География", type="list"),
                    FormFieldSchema(name="brand_tone", label="Тон бренда", type="text"),
                ],
            ),
            FormSectionSchema(
                key="project",
                title="Проект",
                description="Код и название продвигаемого проекта.",
                fields=[
                    FormFieldSchema(
                        name="project_slug",
                        label="Код проекта (slug)",
                        type="text",
                        required=True,
                        help="Латиница/цифры/'-'/'_'.",
                    ),
                    FormFieldSchema(name="project_name", label="Название проекта", type="text"),
                    FormFieldSchema(
                        name="promoted_resource_url", label="Рекламируемый ресурс", type="url"
                    ),
                    FormFieldSchema(
                        name="default_site_url", label="Ссылка по умолчанию", type="url"
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
                    FormFieldSchema(name="priority", label="Приоритет", type="number", default=0),
                    FormFieldSchema(
                        name="intent",
                        label="Интент",
                        type="select",
                        default="commercial",
                        options=["commercial", "informational", "brand", "process", "price"],
                    ),
                ],
            ),
            FormSectionSchema(
                key="media_sources",
                title="Медиа-источники",
                description="Откуда бот берёт фото/видео.",
                repeatable=True,
                fields=[
                    FormFieldSchema(
                        name="source_type",
                        label="Тип источника",
                        type="select",
                        required=True,
                        options=[
                            "yandex_disk",
                            "google_drive",
                            "manual",
                            "upload",
                            "website",
                            "other",
                        ],
                    ),
                    FormFieldSchema(name="title", label="Название", type="text"),
                    FormFieldSchema(name="url", label="Ссылка", type="url"),
                    FormFieldSchema(name="root_folder", label="Корневая папка", type="text"),
                    FormFieldSchema(name="allowed_folders", label="Разрешённые папки", type="list"),
                    FormFieldSchema(name="media_tags", label="Медиа-теги", type="list"),
                ],
            ),
            FormSectionSchema(
                key="platforms",
                title="Платформы публикации",
                description="VK, Telegram, Instagram, YouTube, RuTube. Секрет не возвращается.",
                repeatable=True,
                min_items=1,
                fields=[
                    FormFieldSchema(
                        name="platform_type",
                        label="Платформа",
                        type="select",
                        required=True,
                        options=["vk", "telegram", "instagram", "youtube", "rutube", "other"],
                    ),
                    FormFieldSchema(name="title", label="Название", type="text"),
                    FormFieldSchema(name="api_key", label="Токен/секрет", type="secret"),
                    FormFieldSchema(name="external_id", label="ID (group/channel)", type="text"),
                    FormFieldSchema(name="url", label="Ссылка", type="url"),
                    FormFieldSchema(
                        name="live_enabled",
                        label="Живая публикация",
                        type="bool",
                        default=False,
                        help="Выключено. Живые публикации на этом этапе недоступны.",
                    ),
                    FormFieldSchema(name="tags", label="Теги", type="list"),
                    FormFieldSchema(name="keywords", label="Ключи", type="list"),
                ],
            ),
            FormSectionSchema(
                key="promotion_categories",
                title="Категории продвижения",
                description="Ракурс рекламы: ключи, приоритеты, медиа-теги.",
                repeatable=True,
                min_items=1,
                fields=[
                    FormFieldSchema(name="title", label="Название", type="text", required=True),
                    FormFieldSchema(name="description", label="Описание", type="textarea"),
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
                        name="keyword_queries", label="Ключи (по запросу)", type="list"
                    ),
                    FormFieldSchema(
                        name="resource_titles", label="Платформы (по названию)", type="list"
                    ),
                    FormFieldSchema(
                        name="default_site_url", label="Ссылка по умолчанию", type="url"
                    ),
                    FormFieldSchema(name="cta", label="Призыв к действию", type="text"),
                    FormFieldSchema(name="tone", label="Тон", type="text"),
                ],
            ),
            FormSectionSchema(
                key="publishing_plans",
                title="Расписание публикаций",
                description="Дни, время, платформы, режим. auto_publish недоступен.",
                repeatable=True,
                fields=[
                    FormFieldSchema(
                        name="category_title", label="Категория (по названию)", type="text"
                    ),
                    FormFieldSchema(
                        name="platforms",
                        label="Платформы",
                        type="multiselect",
                        options=["telegram", "vk", "instagram", "youtube", "rutube"],
                    ),
                    FormFieldSchema(
                        name="weekdays",
                        label="Дни недели",
                        type="multiselect",
                        options=["0", "1", "2", "3", "4", "5", "6"],
                    ),
                    FormFieldSchema(
                        name="posts_per_day", label="Постов в день", type="number", default=1
                    ),
                    FormFieldSchema(name="publish_times", label="Время (HH:MM)", type="list"),
                    FormFieldSchema(
                        name="mode",
                        label="Режим",
                        type="select",
                        default="draft",
                        options=["draft", "semi_auto", "auto_schedule"],
                    ),
                    FormFieldSchema(
                        name="timezone", label="Часовой пояс", type="text", default="Europe/Moscow"
                    ),
                    FormFieldSchema(name="start_date", label="Дата старта", type="date"),
                    FormFieldSchema(name="end_date", label="Дата окончания", type="date"),
                ],
            ),
            FormSectionSchema(
                key="billing",
                title="Биллинг",
                description="Тариф, стартовое пополнение (units), принятие условий.",
                fields=[
                    FormFieldSchema(name="tariff_plan_slug", label="Тариф", type="text"),
                    FormFieldSchema(
                        name="starting_topup_amount",
                        label="Стартовое пополнение (units)",
                        type="number",
                    ),
                    FormFieldSchema(
                        name="accept_terms", label="Принимаю условия", type="bool", default=False
                    ),
                ],
            ),
        ]
        return BotSmmFormSchema(
            version="1.0",
            title="SaaS онбординг — личный кабинет",
            sections=sections,
            disabled_modes=["auto_publish"],
            safety_notes=[
                "Живые публикации выключены; auto_publish недоступен.",
                "Секрет платформы не возвращается — только маска.",
                "Депозит и usage — во внутренних units; реальных платежей нет.",
            ],
        )

    # ------------------------------------------------------------------ #
    # Preview / Apply                                                    #
    # ------------------------------------------------------------------ #

    def preview(
        self, db: Session, account_id: int, payload: SaasOnboardingPayload, allow_live: bool = False
    ) -> SaasOnboardingResult:
        """Dry-run: валидирует и показывает, что будет создано (ничего не пишет)."""
        live_warnings = self._check_live(payload, allow_live)
        self._guard_project_ownership(db, account_id, payload)
        crm_payload = self._to_crm_payload(payload)
        crm = self._crm.apply_onboarding_payload(db, crm_payload, dry_run=True)
        billing = billing_repository.get_billing_account_by_account_id(db, account_id)
        return SaasOnboardingResult(
            account_id=account_id,
            dry_run=True,
            project_id=None,
            crm=crm,
            billing_balance_units=billing.balance_units if billing is not None else None,
            warnings=[*live_warnings, "dry-run: изменения в БД не сохранены."],
        )

    def apply(
        self, db: Session, account_id: int, payload: SaasOnboardingPayload, allow_live: bool = False
    ) -> SaasOnboardingResult:
        """Реальный apply: создаёт проект/конфиг под аккаунтом + провижининг биллинга."""
        account = account_repository.get_account_by_id(db, account_id)
        if account is None:
            raise SaasOnboardingError(f"Аккаунт id={account_id} не найден")
        if not payload.billing.accept_terms:
            raise SaasOnboardingError("Необходимо принять условия (accept_terms=true)")
        live_warnings = self._check_live(payload, allow_live)
        # ВАЖНО (изоляция аккаунтов): проверяем ДО CRM-apply, т.к. он мутирует строку
        # проекта по глобальному slug — иначе чужой проект был бы изменён/перепривязан.
        self._guard_project_ownership(db, account_id, payload)

        crm_payload = self._to_crm_payload(payload)
        crm = self._crm.apply_onboarding_payload(db, crm_payload, dry_run=False)

        slug = normalize_slug(payload.project.project_slug)
        project = project_repository.get_project_by_slug(db, slug)
        project_id = project.id if project is not None else None
        # Привязываем к аккаунту только НЕпривязанный проект (новый/seed). Проект
        # другого аккаунта уже отсечён guard-ом выше — чужой не крадём и не мутируем.
        if project is not None and project.account_id is None:
            project.account_id = account_id
            db.commit()
            db.refresh(project)

        # Провижининг биллинга: счёт + стартовое пополнение (идемпотентно).
        self._billing.get_or_create_billing_account(
            db, account_id, payload.billing.tariff_plan_slug
        )
        topup = payload.billing.starting_topup_amount or 0
        if topup > 0:
            self._billing.manual_topup(
                db,
                account_id,
                topup,
                idempotency_key=f"onboarding-topup-{account_id}-{slug}",
                description="Стартовое пополнение (онбординг)",
            )
        balance = self._billing.get_balance(db, account_id).balance_units

        return SaasOnboardingResult(
            account_id=account_id,
            dry_run=False,
            project_id=project_id,
            crm=crm,
            billing_balance_units=balance,
            warnings=[
                *live_warnings,
                "apply выполнен. Публикации НЕ выполнялись, live выключен.",
            ],
        )

    # ------------------------------------------------------------------ #
    # Проекты аккаунта и дашборд                                          #
    # ------------------------------------------------------------------ #

    def list_account_projects(self, db: Session, account_id: int) -> list[Project]:
        """Проекты, привязанные к аккаунту."""
        return project_repository.list_projects_by_account(db, account_id)

    def build_dashboard(self, db: Session, project_id: int) -> ProjectDashboard:
        """Собрать дашборд проекта (конфигурация, контент, ревью, биллинг)."""
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise SaasOnboardingError(f"Проект id={project_id} не найден")

        platforms_count = media_sources_count = categories_count = active_plans_count = 0
        config = crm_repo.get_config_by_project_id(db, project.id)
        if config is not None:
            platforms_count = len(crm_repo.list_resources_by_config(db, config.id))
            media_sources_count = len(crm_repo.list_content_sources_by_config(db, config.id))
            categories = crm_repo.list_categories_by_config(db, config.id)
            categories_count = len(categories)
            for cat in categories:
                active_plans_count += sum(
                    1 for plan in crm_repo.list_plans_by_category(db, cat.id) if plan.is_active
                )

        posts = post_repository.list_posts(db, project_id=project.id, limit=200)
        recent = [
            DashboardRecentPost(id=p.id, title=p.title, status=p.status)
            for p in sorted(posts, key=lambda p: p.id, reverse=True)[:5]
        ]
        posts_needing_review = sum(1 for p in posts if p.status == "needs_review")

        balance: int | None = None
        if project.account_id is not None:
            billing = billing_repository.get_billing_account_by_account_id(db, project.account_id)
            balance = billing.balance_units if billing is not None else None

        actions: list[str] = []
        if platforms_count == 0:
            actions.append("Добавьте платформу публикации (VK/Telegram/…).")
        if media_sources_count == 0:
            actions.append("Добавьте медиа-источник (Яндекс Диск).")
        if categories_count == 0:
            actions.append("Создайте категорию продвижения.")
        if balance is not None and balance <= 0:
            actions.append("Пополните депозит (units) перед запуском генерации.")
        if posts_needing_review > 0:
            actions.append(f"На ревью {posts_needing_review} постов — проверьте и одобрите.")
        actions.append(
            f"Безопасный dry-run прогон категории: POST /saas/projects/{project.id}/run-dry."
        )

        return ProjectDashboard(
            project_id=project.id,
            project_slug=project.slug,
            project_name=project.name,
            account_id=project.account_id,
            website_url=project.website_url,
            platforms_count=platforms_count,
            media_sources_count=media_sources_count,
            categories_count=categories_count,
            active_plans_count=active_plans_count,
            recent_posts=recent,
            posts_needing_review=posts_needing_review,
            billing_balance_units=balance,
            next_recommended_actions=actions,
        )

    # ------------------------------------------------------------------ #
    # Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _guard_project_ownership(
        db: Session, account_id: int, payload: SaasOnboardingPayload
    ) -> None:
        """Отсечь захват чужого проекта: slug глобально уникален, поэтому проект с
        таким slug, принадлежащий ДРУГОМУ аккаунту, трогать нельзя."""
        try:
            slug = normalize_slug(payload.project.project_slug)
        except ValueError:
            return  # некорректный slug — понятную ошибку выдаст CRM-валидация
        existing = project_repository.get_project_by_slug(db, slug)
        if (
            existing is not None
            and existing.account_id is not None
            and existing.account_id != account_id
        ):
            raise SaasOnboardingError(
                f"Проект '{slug}' уже принадлежит другому аккаунту — выберите другой slug"
            )

    def _check_live(self, payload: SaasOnboardingPayload, allow_live: bool) -> list[str]:
        """Проверить запрос live-публикации. Без admin/flag — ошибка; иначе warning."""
        live_platforms = [p.platform_type for p in payload.platforms if p.live_enabled]
        if live_platforms and not allow_live:
            raise SaasOnboardingError(
                f"live_enabled требует прав администратора/флага. Запрошено для: {live_platforms}"
            )
        if live_platforms:
            return [
                f"Запрошена live-публикация для {live_platforms}, но она остаётся "
                "ВЫКЛЮЧЕННОЙ на этом этапе (безопасность)."
            ]
        return []

    def _to_crm_payload(self, payload: SaasOnboardingPayload) -> dict[str, Any]:
        """Смаппить SaaS-пейлоад в CRM-онбординг пейлоад (переиспользование логики)."""
        company = payload.company
        project = payload.project
        return {
            "project": {
                "slug": project.project_slug,
                "name": company.company_name or project.project_name or project.project_slug,
                "display_name": project.project_name
                or company.company_name
                or project.project_slug,
            },
            "site_or_topics": {
                "has_website": company.has_website,
                "website_url": company.website_url,
                "manual_topics": company.manual_topics,
                "reference_sites": [],
                "business_description": company.business_description,
                "geography": company.geography,
                "brand_tone": company.brand_tone,
                "required_review": True,
            },
            "resources": [
                {
                    "resource_type": platform.platform_type,
                    "title": platform.title or platform.platform_type,
                    "api_key": platform.api_key,
                    "external_id": platform.external_id,
                    "url": platform.url,
                    "tags": platform.tags,
                    "keywords": platform.keywords,
                    "live_enabled": False,  # принудительно выключено (безопасность)
                }
                for platform in payload.platforms
            ],
            "keywords": [
                {
                    "query": kw.query,
                    "frequency": kw.frequency,
                    "cluster": kw.cluster,
                    "product": kw.product,
                    "technology": kw.technology,
                    "intent": kw.intent,
                    "priority": kw.priority,
                }
                for kw in payload.keywords
            ],
            "content_sources": [
                {
                    "source_type": source.source_type,
                    "title": source.title or source.source_type,
                    "url": source.url,
                    "root_folder": source.root_folder,
                    "allowed_folders": source.allowed_folders,
                    "media_tags": source.media_tags,
                }
                for source in payload.media_sources
            ],
            "promotion_categories": [
                {
                    "title": cat.title,
                    "description": cat.description,
                    "resource_titles": cat.resource_titles,
                    "keyword_queries": cat.keyword_queries,
                    "product_priorities": cat.product_priorities,
                    "technology_priorities": cat.technology_priorities,
                    "media_tags": cat.media_tags,
                    "default_site_url": cat.default_site_url or project.default_site_url,
                    "cta": cat.cta,
                    "tone": cat.tone,
                }
                for cat in payload.promotion_categories
            ],
            "publishing_plans": [
                {
                    "category_title": plan.category_title,
                    "platforms": plan.platforms,
                    "weekdays": plan.weekdays,
                    "posts_per_day": plan.posts_per_day,
                    "publish_times": plan.publish_times,
                    "mode": plan.mode,
                    "timezone": plan.timezone,
                    "start_date": plan.start_date,
                    "end_date": plan.end_date,
                }
                for plan in payload.publishing_plans
            ],
        }
