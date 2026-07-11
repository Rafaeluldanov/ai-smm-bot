"""Репозиторий слоя «CRM Bot SMM Configurator».

Весь доступ к БД для конфигурации, ресурсов, ключей, источников, категорий,
планов и черновиков онбординга. Секрет ресурса кодируется здесь через
:mod:`app.services.crm_secret_service` — наружу он не выходит.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.crm_bot_smm import (
    CrmBotProjectConfig,
    CrmContentSource,
    CrmKeyword,
    CrmOnboardingDraft,
    CrmPromotionCategory,
    CrmPublishingPlan,
    CrmSmmResource,
)
from app.schemas.crm_bot_smm import (
    CrmBotProjectConfigCreate,
    CrmBotProjectConfigUpdate,
    CrmContentSourceCreate,
    CrmContentSourceUpdate,
    CrmKeywordCreate,
    CrmKeywordUpdate,
    CrmOnboardingDraftCreate,
    CrmOnboardingDraftUpdate,
    CrmPromotionCategoryCreate,
    CrmPromotionCategoryUpdate,
    CrmPublishingPlanCreate,
    CrmPublishingPlanUpdate,
    CrmSmmResourceCreate,
    CrmSmmResourceUpdate,
)
from app.services.crm_secret_service import encrypt_secret, mask_secret

# --------------------------------------------------------------------------- #
# Конфигурация проекта                                                         #
# --------------------------------------------------------------------------- #


def create_config(db: Session, data: CrmBotProjectConfigCreate) -> CrmBotProjectConfig:
    """Создать конфигурацию проекта."""
    config = CrmBotProjectConfig(**data.model_dump())
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def update_config(
    db: Session, config: CrmBotProjectConfig, data: CrmBotProjectConfigUpdate
) -> CrmBotProjectConfig:
    """Частично обновить конфигурацию проекта."""
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(config, field, value)
    db.commit()
    db.refresh(config)
    return config


def get_config_by_id(db: Session, config_id: int) -> CrmBotProjectConfig | None:
    """Вернуть конфигурацию по id или None."""
    return db.get(CrmBotProjectConfig, config_id)


def get_config_by_project_id(db: Session, project_id: int) -> CrmBotProjectConfig | None:
    """Вернуть конфигурацию проекта по project_id или None."""
    stmt = select(CrmBotProjectConfig).where(CrmBotProjectConfig.project_id == project_id)
    return db.scalars(stmt).first()


def get_config_by_crm_external_id(db: Session, crm_external_id: str) -> CrmBotProjectConfig | None:
    """Вернуть конфигурацию по идентификатору из CRM или None."""
    stmt = select(CrmBotProjectConfig).where(CrmBotProjectConfig.crm_external_id == crm_external_id)
    return db.scalars(stmt).first()


def list_configs(db: Session) -> list[CrmBotProjectConfig]:
    """Вернуть все конфигурации (новые — выше)."""
    return list(db.scalars(select(CrmBotProjectConfig).order_by(CrmBotProjectConfig.id.desc())))


# --------------------------------------------------------------------------- #
# Ресурсы (с обработкой секрета)                                               #
# --------------------------------------------------------------------------- #


def _apply_secret(payload: dict[str, Any], api_key: str | None) -> None:
    """Закодировать секрет в payload ресурса (или очистить поля)."""
    if api_key:
        payload["api_key_encrypted"] = encrypt_secret(api_key)
        payload["api_key_masked"] = mask_secret(api_key)


def create_resource(db: Session, data: CrmSmmResourceCreate) -> CrmSmmResource:
    """Создать ресурс. Секрет кодируется, наружу не выходит."""
    payload = data.model_dump()
    api_key = payload.pop("api_key", None)
    payload.setdefault("api_key_encrypted", None)
    payload.setdefault("api_key_masked", None)
    _apply_secret(payload, api_key)
    resource = CrmSmmResource(**payload)
    db.add(resource)
    db.commit()
    db.refresh(resource)
    return resource


def update_resource(
    db: Session, resource: CrmSmmResource, data: CrmSmmResourceUpdate
) -> CrmSmmResource:
    """Частично обновить ресурс. Новый ``api_key`` перекодируется."""
    payload = data.model_dump(exclude_unset=True)
    api_key = payload.pop("api_key", None)
    _apply_secret(payload, api_key)
    for field, value in payload.items():
        setattr(resource, field, value)
    db.commit()
    db.refresh(resource)
    return resource


def get_resource_by_id(db: Session, resource_id: int) -> CrmSmmResource | None:
    """Вернуть ресурс по id или None."""
    return db.get(CrmSmmResource, resource_id)


def get_resource_by_key(
    db: Session, config_id: int, resource_type: str, title: str
) -> CrmSmmResource | None:
    """Найти ресурс по ключу идемпотентности (config_id, resource_type, title)."""
    stmt = select(CrmSmmResource).where(
        CrmSmmResource.config_id == config_id,
        CrmSmmResource.resource_type == resource_type,
        CrmSmmResource.title == title,
    )
    return db.scalars(stmt).first()


def list_resources_by_config(db: Session, config_id: int) -> list[CrmSmmResource]:
    """Вернуть ресурсы конфигурации в порядке создания."""
    stmt = (
        select(CrmSmmResource)
        .where(CrmSmmResource.config_id == config_id)
        .order_by(CrmSmmResource.id)
    )
    return list(db.scalars(stmt))


# --------------------------------------------------------------------------- #
# Platform connections (self-service, v0.3.6)                                  #
# --------------------------------------------------------------------------- #


def list_resources_by_project(db: Session, project_id: int) -> list[CrmSmmResource]:
    """Вернуть ресурсы проекта в порядке создания (все типы платформ)."""
    stmt = (
        select(CrmSmmResource)
        .where(CrmSmmResource.project_id == project_id)
        .order_by(CrmSmmResource.id)
    )
    return list(db.scalars(stmt))


def get_active_resource_by_project_platform(
    db: Session, project_id: int, resource_type: str
) -> CrmSmmResource | None:
    """Найти активное подключение платформы проекта (по project_id + resource_type)."""
    stmt = (
        select(CrmSmmResource)
        .where(
            CrmSmmResource.project_id == project_id,
            CrmSmmResource.resource_type == resource_type,
            CrmSmmResource.is_active.is_(True),
        )
        .order_by(CrmSmmResource.id)
    )
    return db.scalars(stmt).first()


def create_resource_fields(db: Session, fields: dict[str, Any]) -> CrmSmmResource:
    """Создать ресурс из готового словаря полей (секреты уже зашифрованы вызывающим)."""
    resource = CrmSmmResource(**fields)
    db.add(resource)
    db.commit()
    db.refresh(resource)
    return resource


def update_resource_fields(
    db: Session, resource: CrmSmmResource, fields: dict[str, Any]
) -> CrmSmmResource:
    """Обновить ресурс из готового словаря полей (секреты уже зашифрованы вызывающим)."""
    for field, value in fields.items():
        setattr(resource, field, value)
    db.commit()
    db.refresh(resource)
    return resource


# --------------------------------------------------------------------------- #
# Ключевые слова                                                              #
# --------------------------------------------------------------------------- #


def create_keyword(db: Session, data: CrmKeywordCreate) -> CrmKeyword:
    """Создать ключевой запрос."""
    keyword = CrmKeyword(**data.model_dump())
    db.add(keyword)
    db.commit()
    db.refresh(keyword)
    return keyword


def update_keyword(db: Session, keyword: CrmKeyword, data: CrmKeywordUpdate) -> CrmKeyword:
    """Частично обновить ключевой запрос."""
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(keyword, field, value)
    db.commit()
    db.refresh(keyword)
    return keyword


def get_keyword_by_id(db: Session, keyword_id: int) -> CrmKeyword | None:
    """Вернуть ключевой запрос по id или None."""
    return db.get(CrmKeyword, keyword_id)


def get_keyword_by_key(db: Session, config_id: int, query: str) -> CrmKeyword | None:
    """Найти ключ по ключу идемпотентности (config_id, query)."""
    stmt = select(CrmKeyword).where(CrmKeyword.config_id == config_id, CrmKeyword.query == query)
    return db.scalars(stmt).first()


def list_keywords_by_config(db: Session, config_id: int) -> list[CrmKeyword]:
    """Вернуть ключи конфигурации в порядке создания."""
    stmt = select(CrmKeyword).where(CrmKeyword.config_id == config_id).order_by(CrmKeyword.id)
    return list(db.scalars(stmt))


# --------------------------------------------------------------------------- #
# Источники контента                                                          #
# --------------------------------------------------------------------------- #


def create_content_source(db: Session, data: CrmContentSourceCreate) -> CrmContentSource:
    """Создать источник контента."""
    source = CrmContentSource(**data.model_dump())
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def update_content_source(
    db: Session, source: CrmContentSource, data: CrmContentSourceUpdate
) -> CrmContentSource:
    """Частично обновить источник контента."""
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(source, field, value)
    db.commit()
    db.refresh(source)
    return source


def get_content_source_by_id(db: Session, source_id: int) -> CrmContentSource | None:
    """Вернуть источник контента по id или None."""
    return db.get(CrmContentSource, source_id)


def get_content_source_by_key(
    db: Session, config_id: int, source_type: str, title: str, url: str | None
) -> CrmContentSource | None:
    """Найти источник по ключу (config_id, source_type, title, url).

    ``url`` может быть None — сравнение выполняется в Python (устойчиво к NULL).
    """
    stmt = select(CrmContentSource).where(
        CrmContentSource.config_id == config_id,
        CrmContentSource.source_type == source_type,
        CrmContentSource.title == title,
    )
    for source in db.scalars(stmt):
        if (source.url or None) == (url or None):
            return source
    return None


def list_content_sources_by_config(db: Session, config_id: int) -> list[CrmContentSource]:
    """Вернуть источники контента конфигурации в порядке создания."""
    stmt = (
        select(CrmContentSource)
        .where(CrmContentSource.config_id == config_id)
        .order_by(CrmContentSource.id)
    )
    return list(db.scalars(stmt))


# --------------------------------------------------------------------------- #
# Категории продвижения                                                       #
# --------------------------------------------------------------------------- #


def create_category(db: Session, data: CrmPromotionCategoryCreate) -> CrmPromotionCategory:
    """Создать категорию продвижения."""
    category = CrmPromotionCategory(**data.model_dump())
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


def update_category(
    db: Session, category: CrmPromotionCategory, data: CrmPromotionCategoryUpdate
) -> CrmPromotionCategory:
    """Частично обновить категорию продвижения."""
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(category, field, value)
    db.commit()
    db.refresh(category)
    return category


def get_category_by_id(db: Session, category_id: int) -> CrmPromotionCategory | None:
    """Вернуть категорию по id или None."""
    return db.get(CrmPromotionCategory, category_id)


def get_category_by_key(db: Session, config_id: int, title: str) -> CrmPromotionCategory | None:
    """Найти категорию по ключу идемпотентности (config_id, title)."""
    stmt = select(CrmPromotionCategory).where(
        CrmPromotionCategory.config_id == config_id,
        CrmPromotionCategory.title == title,
    )
    return db.scalars(stmt).first()


def list_categories_by_config(db: Session, config_id: int) -> list[CrmPromotionCategory]:
    """Вернуть категории конфигурации в порядке создания."""
    stmt = (
        select(CrmPromotionCategory)
        .where(CrmPromotionCategory.config_id == config_id)
        .order_by(CrmPromotionCategory.id)
    )
    return list(db.scalars(stmt))


# --------------------------------------------------------------------------- #
# Планы публикаций                                                            #
# --------------------------------------------------------------------------- #


def create_plan(db: Session, data: CrmPublishingPlanCreate) -> CrmPublishingPlan:
    """Создать план публикаций."""
    plan = CrmPublishingPlan(**data.model_dump())
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def update_plan(
    db: Session, plan: CrmPublishingPlan, data: CrmPublishingPlanUpdate
) -> CrmPublishingPlan:
    """Частично обновить план публикаций."""
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(plan, field, value)
    db.commit()
    db.refresh(plan)
    return plan


def get_plan_by_id(db: Session, plan_id: int) -> CrmPublishingPlan | None:
    """Вернуть план по id или None."""
    return db.get(CrmPublishingPlan, plan_id)


def get_first_plan_by_category(db: Session, category_id: int) -> CrmPublishingPlan | None:
    """Первый план категории (для случая «один план на категорию»)."""
    plans = list_plans_by_category(db, category_id)
    return plans[0] if plans else None


def find_plan_by_schedule(
    db: Session,
    category_id: int,
    platforms: list[str],
    weekdays: list[int],
    publish_times: list[str],
) -> CrmPublishingPlan | None:
    """Найти план категории по расписанию (платформы, дни, время) — сравнение в Python."""
    for plan in list_plans_by_category(db, category_id):
        if (
            list(plan.platforms or []) == list(platforms)
            and list(plan.weekdays or []) == list(weekdays)
            and list(plan.publish_times or []) == list(publish_times)
        ):
            return plan
    return None


def list_plans_by_category(db: Session, category_id: int) -> list[CrmPublishingPlan]:
    """Вернуть планы категории в порядке создания."""
    stmt = (
        select(CrmPublishingPlan)
        .where(CrmPublishingPlan.category_id == category_id)
        .order_by(CrmPublishingPlan.id)
    )
    return list(db.scalars(stmt))


def list_plans_by_config(db: Session, config_id: int) -> list[CrmPublishingPlan]:
    """Вернуть планы конфигурации в порядке создания."""
    stmt = (
        select(CrmPublishingPlan)
        .where(CrmPublishingPlan.config_id == config_id)
        .order_by(CrmPublishingPlan.id)
    )
    return list(db.scalars(stmt))


# --------------------------------------------------------------------------- #
# Черновики онбординга                                                         #
# --------------------------------------------------------------------------- #


def create_draft(db: Session, data: CrmOnboardingDraftCreate) -> CrmOnboardingDraft:
    """Создать черновик онбординга."""
    draft = CrmOnboardingDraft(**data.model_dump())
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def update_draft(
    db: Session, draft: CrmOnboardingDraft, data: CrmOnboardingDraftUpdate
) -> CrmOnboardingDraft:
    """Частично обновить черновик онбординга."""
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(draft, field, value)
    db.commit()
    db.refresh(draft)
    return draft


def get_draft_by_id(db: Session, draft_id: int) -> CrmOnboardingDraft | None:
    """Вернуть черновик онбординга по id или None."""
    return db.get(CrmOnboardingDraft, draft_id)


def list_drafts(db: Session) -> list[CrmOnboardingDraft]:
    """Вернуть все черновики онбординга (новые — выше)."""
    return list(db.scalars(select(CrmOnboardingDraft).order_by(CrmOnboardingDraft.id.desc())))
