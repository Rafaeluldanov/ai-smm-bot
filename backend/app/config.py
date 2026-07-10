"""Конфигурация приложения на базе Pydantic Settings.

Все значения читаются из переменных окружения (или файла ``.env``).
Секреты и токены НИКОГДА не хранятся в коде — только в окружении.
"""

from functools import lru_cache
from urllib.parse import urlparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Путь callback VK OAuth (добавляется к PUBLIC_APP_URL, если redirect не задан явно).
VK_OAUTH_CALLBACK_PATH = "/integrations/vk/oauth/callback"
# Путь callback Instagram OAuth (справочный Redirect URI для Meta App, если не задан).
INSTAGRAM_OAUTH_CALLBACK_PATH = "/integrations/instagram/oauth/callback"


class Settings(BaseSettings):
    """Настройки приложения.

    Имена полей сопоставляются с переменными окружения без учёта регистра,
    поэтому поле ``app_name`` читается из переменной ``APP_NAME`` и т. д.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Приложение ---
    app_name: str = "ai-smm-bot"
    app_env: str = "local"

    # --- Безопасность SaaS-платформы ---
    # AUTH_TOKEN_SECRET — секрет для будущей реальной auth (JWT/сессии). В production
    # обязателен; dev-токен-заглушка недопустима. audit_log_enabled — вести ли аудит.
    # security_hide_legacy_projects_in_prod — прятать проекты без account_id в prod.
    # paid_actions_enforced — требовать баланс/списание для платных действий (dev может
    # выключить). security_require_auth — форсировать авторизацию на защищённых роутах
    # даже вне production (в production включено всегда).
    auth_token_secret: str = ""
    audit_log_enabled: bool = True
    security_hide_legacy_projects_in_prod: bool = True
    paid_actions_enforced: bool = True
    security_require_auth: bool = False

    # --- Хранилища ---
    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/ai_smm_bot"
    redis_url: str = "redis://localhost:6379/0"

    # --- Внешние интеграции (заполняются на соответствующих этапах) ---
    yandex_disk_token: str | None = None
    yandex_disk_base_url: str = "https://cloud-api.yandex.net/v1/disk"
    yandex_disk_root_path: str = "/SMM_BOT"
    # Публичная папка Яндекс Диска (альтернатива OAuth-токену). Если
    # yandex_disk_public_mode=true — sync-media работает по публичной ссылке.
    yandex_disk_public_smm_url: str = ""
    yandex_disk_public_mode: bool = False
    yandex_disk_public_root_folder: str = "SMM"
    # Токены автопостинга (Этап 7). Пустые значения трактуются как «не задано»:
    # реальная публикация выдаст понятную ошибку, но API и тесты работают без них.
    telegram_bot_token: str = ""
    telegram_default_channel_id: str | None = None
    vk_access_token: str = ""
    vk_default_group_id: str | None = None
    instagram_access_token: str = ""
    instagram_business_account_id: str | None = None
    # Instagram Graph API / OAuth (Meta App). app_id, redirect_uri и user_id —
    # НЕсекретные справочные значения (их можно показывать в UI/гайде); app_secret и
    # access_token — СЕКРЕТЫ: в UI отображается только факт наличия/маска, само
    # значение НИКОГДА не попадает в HTML и не логируется.
    instagram_app_id: str = ""
    instagram_app_secret: str = ""
    instagram_redirect_uri: str = ""
    instagram_user_id: str | None = None
    # Видео-платформы (adapter-скелеты; live пока не реализован).
    youtube_access_token: str = ""
    youtube_channel_id: str | None = None
    rutube_access_token: str = ""
    rutube_channel_id: str | None = None

    # Живая (РЕАЛЬНАЯ) публикация в соцсети. По умолчанию ОТКЛЮЧЕНА: без явного
    # флага отправка невозможна (защита от случайной публикации). Для
    # Instagram/YouTube/RuTube даже с флагом live пока не реализован (PublishError).
    telegram_live_publishing_enabled: bool = False
    vk_live_publishing_enabled: bool = False
    instagram_live_publishing_enabled: bool = False
    youtube_live_publishing_enabled: bool = False
    rutube_live_publishing_enabled: bool = False

    # Максимум фото в одном Telegram-посте с альбомом (sendMediaGroup). Telegram
    # допускает до 10 медиа в одной группе.
    telegram_media_group_max_photos: int = 10

    # Максимум фото в одном VK-посте с группой медиа (safety-cap загрузки вложений).
    # По умолчанию 5; размер группы дополнительно ограничивается CLI-флагом
    # ``--limit-media`` при создании поста.
    vk_media_group_max_photos: int = 5

    # --- VK API photo upload strategy (без OAuth/браузера) ---
    # wall  — photos.getWallUploadServer/saveWallPhoto (падает error 27 у community token);
    # album — photos.getUploadServer/photos.save в альбом группы;
    # auto  — сначала wall, при error 27 — album.
    vk_photo_upload_strategy: str = "auto"
    vk_photo_album_id: str | None = None
    vk_photo_album_title: str = "AI SMM Bot uploads"
    # Разрешить probe-команде реально загружать тестовое фото (без wall.post). По
    # умолчанию false — probe делает только безопасные read-проверки.
    vk_photo_probe_allow_upload: bool = False

    # --- SEO-заполнение VK-группы (SEO VK Group Setup) ---
    # Реальные изменения оформления VK-группы (название/описание/статус/закреп/меню)
    # по умолчанию ОТКЛЮЧЕНЫ: apply работает только в режиме preview/dry-run. Даже с
    # флагом реальные вызовы VK API оформления на этом этапе не выполняются.
    vk_group_setup_live_enabled: bool = False
    # Проекты, которым разрешено SEO-заполнение группы (через запятую).
    vk_group_setup_allowed_projects: str = "teeon,fabric-souvenirs"

    # --- Публичный адрес приложения (для VK OAuth callback и ссылок в UI) ---
    # Продакшн-домен с HTTPS; из него выводится VK_OAUTH_REDIRECT_URI, если тот пуст.
    public_app_url: str = "https://app.teeon.ru"

    # --- VK OAuth (подключение ПОЛЬЗОВАТЕЛЬСКОГО токена через кнопку) ---
    # Standalone-приложение VK для OAuth: пользователь сам выдаёт доступ, мы НЕ
    # используем ключ сообщества для фото. ``vk_app_secret`` не логируется и не
    # отдаётся наружу; полученный user-token хранится в секрете ресурса (маска).
    vk_app_id: str = ""
    vk_app_secret: str = ""
    # Пусто ⇒ выводится из PUBLIC_APP_URL + callback-путь (см. model_validator ниже).
    vk_oauth_redirect_uri: str = ""
    vk_oauth_scope: str = "wall,photos,groups,offline"

    @model_validator(mode="after")
    def _resolve_vk_oauth_redirect(self) -> "Settings":
        """Вывести VK_OAUTH_REDIRECT_URI из PUBLIC_APP_URL, если не задан явно."""
        if not self.vk_oauth_redirect_uri.strip():
            self.vk_oauth_redirect_uri = (
                f"{self.public_app_url.rstrip('/')}{VK_OAUTH_CALLBACK_PATH}"
            )
        return self

    # --- AI-провайдер ---
    ai_provider: str = "stub"
    ai_api_key: str = ""
    # Модель и цены токенов провайдера (USD за 1M токенов). НЕ хардкодятся в коде —
    # задаются здесь/в .env, чтобы юнит-экономику можно было пересчитать без правок
    # логики. Значения по умолчанию — ориентир, реальные тарифы обновляются в .env.
    ai_pricing_model: str = "gpt-5.4-mini"
    ai_input_usd_per_1m: float = 0.75
    ai_output_usd_per_1m: float = 4.50

    # --- Биллинг / юнит-экономика (units = внутренняя валюта Botfleet) ---
    # себестоимость_usd = input/1M*in_price + output/1M*out_price
    # цена_клиента_usd  = себестоимость_usd * markup_multiplier
    # units = max(min_units, ceil(цена_клиента_usd * usd_to_unit_rate))
    billing_markup_multiplier: float = 2.0
    billing_usd_to_unit_rate: float = 100.0
    billing_min_post_units: int = 5
    billing_min_analytics_units: int = 3
    # Ориентировочная цена 1 unit в рублях (для суммы счёта; реальных платежей нет).
    billing_unit_price_rub: float = 1.0

    # --- Аналитика: фиксированные цены по глубине (units за пост) ---
    analytics_light_units: int = 10
    analytics_standard_units: int = 20
    analytics_deep_units: int = 40

    # --- Платежи (Россия). РЕАЛЬНЫЕ ПЛАТЕЖИ ВЫКЛЮЧЕНЫ по умолчанию ---
    # Без payments_live_enabled=true все счета создаются как mock/sandbox; баланс
    # пополняется только после статуса paid (mock-pay/webhook). Секреты провайдеров
    # читаются из окружения, в код не хардкодятся, в UI показываются только маской.
    payments_live_enabled: bool = False
    payments_default_provider: str = "mock"
    payments_success_return_url: str = ""
    payments_fail_return_url: str = ""
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    yookassa_webhook_secret: str = ""
    tbank_terminal_key: str = ""
    tbank_password: str = ""
    cloudpayments_public_id: str = ""
    cloudpayments_api_secret: str = ""
    robokassa_merchant_login: str = ""
    robokassa_password1: str = ""
    robokassa_password2: str = ""

    # --- Улучшение медиа (Media Enhancement) ---
    # Локальная обработка изображений (brightness/contrast, resize, конвертация).
    # Оригиналы НЕ изменяются — создаются производные копии (MediaAssetVariant).
    media_enhancement_enabled: bool = False
    media_enhancement_storage_dir: str = "backend/data/enhanced_media"
    media_enhancement_max_image_mb: int = 25
    media_enhancement_default_profile: str = "social_safe"
    media_enhancement_output_format: str = "jpg"
    media_enhancement_jpeg_quality: int = 92

    # --- Производные свойства (готовность к боевому запуску) ---

    @property
    def is_production(self) -> bool:
        """Запущено ли приложение в production-окружении."""
        return self.app_env.strip().lower() in {"production", "prod"}

    @property
    def is_local(self) -> bool:
        """Локальное/тестовое окружение."""
        return self.app_env.strip().lower() in {"local", "dev", "development", "test"}

    @property
    def database_is_sqlite(self) -> bool:
        """Использует ли БД SQLite (для prod ожидается PostgreSQL)."""
        return self.database_url.strip().lower().startswith("sqlite")

    @property
    def telegram_configured(self) -> bool:
        """Готов ли Telegram к публикации (есть токен и канал по умолчанию)."""
        return bool(self.telegram_bot_token and self.telegram_default_channel_id)

    @property
    def vk_configured(self) -> bool:
        """Готов ли VK к публикации (есть токен и группа по умолчанию)."""
        return bool(self.vk_access_token and self.vk_default_group_id)

    @property
    def vk_oauth_configured(self) -> bool:
        """Готов ли VK OAuth-поток (есть app_id, app_secret и redirect_uri)."""
        return bool(self.vk_app_id and self.vk_app_secret and self.vk_oauth_redirect_uri)

    @property
    def vk_oauth_base_domain(self) -> str:
        """Базовый домен для VK ID (host из redirect_uri / public_app_url)."""
        parsed = urlparse(self.vk_oauth_redirect_uri or self.public_app_url)
        return parsed.hostname or ""

    @property
    def telegram_live_publishing_configured(self) -> bool:
        """Включена ли РЕАЛЬНАЯ публикация в Telegram (флаг + токен + канал)."""
        return (
            self.telegram_live_publishing_enabled
            and bool(self.telegram_bot_token)
            and bool(self.telegram_default_channel_id)
        )

    @property
    def vk_live_publishing_configured(self) -> bool:
        """Включена ли РЕАЛЬНАЯ публикация во VK (флаг + токен + группа)."""
        return (
            self.vk_live_publishing_enabled
            and bool(self.vk_access_token)
            and bool(self.vk_default_group_id)
        )

    @property
    def instagram_live_publishing_configured(self) -> bool:
        """Заданы флаг+токен+аккаунт Instagram (сам live-клиент пока не реализован)."""
        return (
            self.instagram_live_publishing_enabled
            and bool(self.instagram_access_token)
            and bool(self.instagram_business_account_id)
        )

    @property
    def instagram_redirect_uri_effective(self) -> str:
        """Redirect URI для Instagram OAuth: из настройки или из PUBLIC_APP_URL.

        Справочное значение для настройки Meta App (сам OAuth-эндпоинт появится на
        отдельном этапе). Всегда НЕсекретно — можно показывать в UI/гайде.
        """
        explicit = self.instagram_redirect_uri.strip()
        if explicit:
            return explicit
        return f"{self.public_app_url.rstrip('/')}{INSTAGRAM_OAUTH_CALLBACK_PATH}"

    @property
    def instagram_effective_user_id(self) -> str:
        """Instagram User ID (external_id): из INSTAGRAM_USER_ID или business account."""
        return (self.instagram_user_id or self.instagram_business_account_id or "").strip()

    @property
    def instagram_oauth_configured(self) -> bool:
        """Заданы ли App ID + App Secret + Redirect URI для Instagram OAuth."""
        return bool(
            self.instagram_app_id
            and self.instagram_app_secret
            and self.instagram_redirect_uri_effective
        )

    @property
    def youtube_live_publishing_configured(self) -> bool:
        """Заданы флаг+токен+канал YouTube (сам live-клиент пока не реализован)."""
        return (
            self.youtube_live_publishing_enabled
            and bool(self.youtube_access_token)
            and bool(self.youtube_channel_id)
        )

    @property
    def rutube_live_publishing_configured(self) -> bool:
        """Заданы флаг+токен+канал RuTube (сам live-клиент пока не реализован)."""
        return (
            self.rutube_live_publishing_enabled
            and bool(self.rutube_access_token)
            and bool(self.rutube_channel_id)
        )

    @property
    def vk_group_setup_allowed_projects_list(self) -> list[str]:
        """Список project_slug, которым разрешено SEO-заполнение VK-группы."""
        return [
            slug.strip() for slug in self.vk_group_setup_allowed_projects.split(",") if slug.strip()
        ]

    @property
    def yandex_disk_configured(self) -> bool:
        """Задан ли токен Яндекс Диска (приватный OAuth-режим)."""
        return bool(self.yandex_disk_token)

    @property
    def yandex_disk_public_configured(self) -> bool:
        """Задана ли публичная ссылка на папку SMM (публичный режим)."""
        return bool(self.yandex_disk_public_smm_url)

    @property
    def ai_configured(self) -> bool:
        """Подключён ли реальный AI-провайдер (не заглушка и есть ключ)."""
        return self.ai_provider.strip().lower() != "stub" and bool(self.ai_api_key)

    @property
    def media_enhancement_configured(self) -> bool:
        """Готово ли локальное улучшение медиа (задана папка для копий).

        Внешние ключи не нужны: обработка идёт локально через Pillow.
        """
        return bool(self.media_enhancement_storage_dir.strip())


@lru_cache
def get_settings() -> Settings:
    """Вернуть кешированный экземпляр настроек."""
    return Settings()
