"""Модели слоя конфигурации «CRM Bot SMM Onboarding / Configurator».

Позволяют человеку из внешней CRM заполнить форму «БОТ СММ»: проект, сайт или
темы, ресурсы продвижения, ключевые слова, источники контента, категории
продвижения и план публикаций. На основе этих данных строятся SEO-профиль,
контент-план и безопасный semi_auto-прогон (без реальных публикаций).

ВАЖНО (безопасность):
- секрет ресурса хранится в ``api_key_encrypted`` и НИКОГДА не возвращается через
  API — наружу отдаются только ``api_key_present`` и ``api_key_masked``
  (см. :mod:`app.schemas.crm_bot_smm` и :mod:`app.services.crm_secret_service`);
- ``live_enabled`` по умолчанию false; живые публикации на этом этапе выключены.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class CrmBotProjectConfig(Base, TimestampMixin):
    """Конфигурация проекта «БОТ СММ», заполняемая в CRM."""

    __tablename__ = "crm_bot_project_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Идентификатор записи на стороне внешней CRM (для связки и идемпотентности).
    crm_external_id: Mapped[str | None] = mapped_column(String(255), index=True, default=None)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    website_url: Mapped[str | None] = mapped_column(String(512), default=None)
    has_website: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    manual_topics: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    reference_sites: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    business_description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    geography: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    brand_tone: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    forbidden_phrases: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    required_review: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # draft | active | paused | archived
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True, nullable=False)


class CrmSmmResource(Base, TimestampMixin):
    """Ресурс продвижения (VK / Telegram / Яндекс Диск / сайт / другое).

    Секрет хранится в ``api_key_encrypted`` (сервисный слой шифрования — заглушка,
    заменяется на KMS/Fernet). Наружу секрет НЕ отдаётся.
    """

    __tablename__ = "crm_smm_resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    config_id: Mapped[int] = mapped_column(
        ForeignKey("crm_bot_project_configs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # vk | telegram | yandex_disk | website | other
    resource_type: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # TODO(security): заменить хранение на реальное шифрование (KMS/Fernet).
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, default=None)
    api_key_masked: Mapped[str | None] = mapped_column(String(64), default=None)
    external_id: Mapped[str | None] = mapped_column(String(255), default=None)
    url: Mapped[str | None] = mapped_column(String(512), default=None)
    yandex_public_url: Mapped[str | None] = mapped_column(String(512), default=None)
    yandex_root_folder: Mapped[str | None] = mapped_column(String(255), default=None)
    tags: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    keywords: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    live_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # --- Self-service подключение платформы (v0.3.6) ---
    # app_id — НЕсекретный идентификатор приложения (VK/Meta); app_secret — секрет
    # (хранится зашифрованным, наружу только маска). Основной токен площадки —
    # api_key_encrypted (bot token / access token). redirect_uri и пр. — в metadata.
    app_id: Mapped[str | None] = mapped_column(String(255), default=None)
    app_secret_encrypted: Mapped[str | None] = mapped_column(Text, default=None)
    app_secret_masked: Mapped[str | None] = mapped_column(String(64), default=None)
    # draft | connected | error — состояние подключения (по результату проверки).
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True, nullable=False)
    # Результат последней безопасной проверки подключения (без секретов).
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_check_status: Mapped[str | None] = mapped_column(String(20), default=None)
    last_check_message: Mapped[str | None] = mapped_column(String(1000), default=None)
    # Прочие несекретные параметры подключения (redirect_uri, default_cta и т. п.).
    resource_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )


class CrmKeyword(Base, TimestampMixin):
    """Ключевой запрос продвижения (SEO-семантика проекта)."""

    __tablename__ = "crm_keywords"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    config_id: Mapped[int] = mapped_column(
        ForeignKey("crm_bot_project_configs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    resource_id: Mapped[int | None] = mapped_column(
        ForeignKey("crm_smm_resources.id", ondelete="SET NULL"), index=True, default=None
    )
    query: Mapped[str] = mapped_column(String(512), nullable=False)
    frequency: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cluster: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    product: Mapped[str | None] = mapped_column(String(255), default=None)
    technology: Mapped[str | None] = mapped_column(String(255), default=None)
    # commercial | informational | brand | process | price
    intent: Mapped[str] = mapped_column(String(20), default="commercial", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class CrmContentSource(Base, TimestampMixin):
    """Источник контента (Яндекс Диск / сайт / ручной ввод / загрузка)."""

    __tablename__ = "crm_content_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    config_id: Mapped[int] = mapped_column(
        ForeignKey("crm_bot_project_configs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # yandex_disk | website | manual | upload
    source_type: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str | None] = mapped_column(String(512), default=None)
    root_folder: Mapped[str | None] = mapped_column(String(255), default=None)
    allowed_folders: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    media_tags: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class CrmPromotionCategory(Base, TimestampMixin):
    """Категория продвижения — связка ресурсов, ключей, приоритетов и медиа-тегов."""

    __tablename__ = "crm_promotion_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    config_id: Mapped[int] = mapped_column(
        ForeignKey("crm_bot_project_configs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    resource_ids: Mapped[list[int]] = mapped_column(JSONType, default=list, nullable=False)
    keyword_ids: Mapped[list[int]] = mapped_column(JSONType, default=list, nullable=False)
    product_priorities: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
    technology_priorities: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
    media_tags: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    default_site_url: Mapped[str | None] = mapped_column(String(512), default=None)
    cta: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tone: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    require_review: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # draft | active | paused | archived
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True, nullable=False)


class CrmPublishingPlan(Base, TimestampMixin):
    """План публикаций категории (расписание, платформы, режим)."""

    __tablename__ = "crm_publishing_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    config_id: Mapped[int] = mapped_column(
        ForeignKey("crm_bot_project_configs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("crm_promotion_categories.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Дни недели 0..6 (Пн=0).
    weekdays: Mapped[list[int]] = mapped_column(JSONType, default=list, nullable=False)
    posts_per_day: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # Время публикаций "HH:MM".
    publish_times: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    platforms: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    # draft | semi_auto | auto_schedule | auto_publish
    mode: Mapped[str] = mapped_column(String(20), default="draft", index=True, nullable=False)
    start_date: Mapped[str | None] = mapped_column(String(20), default=None)
    end_date: Mapped[str | None] = mapped_column(String(20), default=None)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class CrmOnboardingDraft(Base, TimestampMixin):
    """Черновик онбординга: незавершённая форма из CRM (payload + ошибки)."""

    __tablename__ = "crm_onboarding_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True, default=None
    )
    step: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    validation_errors: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    # draft | validated | applied | archived
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True, nullable=False)
