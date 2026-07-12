"""Конфигурация приложения на базе Pydantic Settings.

Все значения читаются из переменных окружения (или файла ``.env``).
Секреты и токены НИКОГДА не хранятся в коде — только в окружении.
"""

from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Dev-фолбэк секрета подписи auth-токенов (используется, если AUTH_TOKEN_SECRET пуст).
# В production считается «не настроенным» — приложение падает на старте/readiness.
DEV_AUTH_SECRET_FALLBACK = "botfleet-dev-auth-secret-not-for-production"
_KNOWN_WEAK_SECRETS = frozenset(
    {"", "change-me", "changeme", "secret", "dev", "test", DEV_AUTH_SECRET_FALLBACK}
)

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
    # Публичный базовый URL и уровень логирования (для production-деплоя).
    app_base_url: str = ""
    log_level: str = "INFO"

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

    # --- Auth / session (v0.3.2 production hardening) ---
    # Access/refresh-токены (HMAC-SHA256, формат header.payload.signature). В production
    # AUTH_TOKEN_SECRET обязателен; dev-токен-заглушка запрещена (auth_allow_dev_token).
    auth_access_token_expire_minutes: int = 30
    auth_refresh_token_expire_days: int = 30
    auth_session_cookie_name: str = "botfleet_session"
    auth_refresh_cookie_name: str = "botfleet_refresh"
    auth_cookie_secure: bool = False
    auth_cookie_samesite: str = "lax"
    auth_cookie_httponly: bool = True
    # Ставить ли access-cookie при логине (cookie-auth). По умолчанию false: SPA/тесты
    # используют Authorization-заголовок; refresh-cookie ставится всегда (для /auth/refresh).
    auth_cookie_auth_enabled: bool = False
    auth_allow_dev_token: bool = True
    auth_require_auth: bool = False

    # --- CSRF (для cookie-auth) ---
    csrf_protection_enabled: bool = False
    csrf_cookie_name: str = "botfleet_csrf"

    # --- Rate limiting (in-memory MVP; для распределённого prod — Redis) ---
    rate_limit_enabled: bool = False
    rate_limit_auth_per_minute: int = 10
    rate_limit_api_per_minute: int = 120
    rate_limit_payment_per_minute: int = 30
    # Публичный media-proxy GET (/media/public/{token}) — базовый IP-лимит.
    rate_limit_media_per_minute: int = 240

    # --- Security headers ---
    security_headers_enabled: bool = True

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

    # --- Импорт метрик из платформенных API (v0.4.1). ВЫКЛЮЧЕНО по умолчанию: ---
    # без явного флага реальные внешние вызовы не выполняются (demo/manual/estimated —
    # всегда без сети). Глобальный рубильник + переключатели по площадкам.
    platform_metrics_api_enabled: bool = False
    telegram_metrics_api_enabled: bool = False
    vk_metrics_api_enabled: bool = False
    instagram_metrics_api_enabled: bool = False
    # Платный ли demo-импорт (по умолчанию бесплатный).
    metrics_demo_import_paid: bool = False

    # --- A/B-тестирование и оптимизация тем (v0.4.2) ---
    # A/B-эксперименты создаются через UI/API. Авто-применение winner к будущим
    # расписаниям и авто-создание экспериментов worker-ом ВЫКЛЮЧЕНЫ по умолчанию.
    # Live-публикаций это не подразумевает.
    ab_testing_enabled: bool = True
    ab_testing_auto_winner_enabled: bool = False
    ab_testing_default_variant_count: int = 2
    ab_testing_max_variants: int = 3
    ab_testing_min_confidence_to_auto_apply: float = 0.7
    schedule_experiments_enabled: bool = False
    topic_optimization_enabled: bool = True
    topic_optimization_recency_days: int = 60
    topic_optimization_max_recommendations: int = 10

    # --- Предложения экспериментов worker-ом (v0.4.3) ---
    # Worker может предлагать эксперименты/темы, но НЕ публикует live. Генерация
    # предложений worker-ом и авто-создание экспериментов ВЫКЛЮЧЕНЫ по умолчанию.
    experiment_suggestions_enabled: bool = True
    experiment_suggestions_worker_enabled: bool = False
    experiment_suggestions_dry_run: bool = True
    experiment_suggestions_auto_create: bool = False
    experiment_suggestions_max_per_tick: int = 5
    experiment_suggestions_max_active_per_project: int = 20
    experiment_suggestions_min_confidence: float = 0.55
    experiment_suggestions_cooldown_hours: int = 24
    experiment_suggestions_expire_days: int = 14
    experiment_suggestions_require_review: bool = True

    # --- Автовыбор темы worker-ом (v0.4.4) ---
    # Worker сам выбирает тему/CTA/формат/медиа-стратегию для ближайшего слота по
    # learning profile + метрикам + feedback + A/B winners + suggestions, но НЕ публикует
    # live. Автовыбор worker-ом ВЫКЛЮЧЕН по умолчанию; dry-run по умолчанию.
    auto_topic_selection_enabled: bool = True
    auto_topic_selection_worker_enabled: bool = False
    auto_topic_selection_dry_run: bool = True
    auto_topic_selection_min_confidence: float = 0.55
    auto_topic_selection_max_alternatives: int = 5
    auto_topic_selection_recency_days: int = 60
    auto_topic_selection_fatigue_window_days: int = 14
    auto_topic_selection_require_media_for_media_plans: bool = False
    auto_topic_selection_use_ab_winners: bool = True
    auto_topic_selection_use_experiment_suggestions: bool = True
    auto_topic_selection_use_metrics: bool = True
    auto_topic_selection_use_client_feedback: bool = True
    auto_topic_selection_fallback_to_crm_category: bool = True

    # --- Автовыбор медиа worker-ом (v0.4.5) ---
    # Worker сам выбирает media strategy и конкретные медиа для слота по теме/тегам/
    # платформе/обучению/A-B winners/метрикам/доступности, но НЕ публикует live и НЕ создаёт
    # публичные ссылки автоматически. Автовыбор worker-ом ВЫКЛЮЧЕН по умолчанию; dry-run.
    auto_media_selection_enabled: bool = True
    auto_media_selection_worker_enabled: bool = False
    auto_media_selection_dry_run: bool = True
    auto_media_selection_min_confidence: float = 0.50
    auto_media_selection_recency_days: int = 60
    auto_media_selection_fatigue_window_days: int = 14
    auto_media_selection_max_images_telegram: int = 10
    auto_media_selection_max_images_vk: int = 5
    auto_media_selection_max_images_instagram: int = 10
    auto_media_selection_require_media_for_media_plans: bool = False
    auto_media_selection_use_ab_winners: bool = True
    auto_media_selection_use_metrics: bool = True
    auto_media_selection_use_client_feedback: bool = True
    auto_media_selection_create_public_links: bool = False

    # --- Оценка качества медиа (v0.4.6) ---
    # Правило-ориентированная оценка качества/релевантности/свежести/уникальности/пригодности
    # медиа + выявление дублей. БЕЗ внешнего AI и БЕЗ live-публикаций. Оценка worker-ом
    # ВЫКЛЮЧЕНА по умолчанию; dry-run; авто-ретегирование выключено.
    media_quality_scoring_enabled: bool = True
    media_quality_scoring_worker_enabled: bool = False
    media_quality_scoring_dry_run: bool = True
    media_quality_min_good_score: int = 70
    media_quality_min_excellent_score: int = 85
    media_quality_recency_days: int = 60
    media_quality_fatigue_window_days: int = 14
    media_quality_max_snapshots_per_asset: int = 20
    media_quality_dedup_enabled: bool = True
    media_quality_platform_weighting_enabled: bool = True
    media_quality_auto_retags_enabled: bool = False
    media_quality_external_ai_enabled: bool = False

    # --- Fingerprint и дедупликация медиа (v0.4.7) ---
    # Безопасные локальные fingerprint (sha256/perceptual/average/difference hash + сигнатуры)
    # и кластеры дублей. БЕЗ внешнего AI/vision, БЕЗ сети по умолчанию (Yandex-скачивание
    # выключено), БЕЗ авто-удаления/скрытия. Fingerprint worker-ом ВЫКЛЮЧЕН по умолчанию; dry-run.
    media_fingerprinting_enabled: bool = True
    media_fingerprinting_worker_enabled: bool = False
    media_fingerprinting_dry_run: bool = True
    media_fingerprinting_max_assets_per_run: int = 200
    media_fingerprinting_use_image_bytes: bool = True
    media_fingerprinting_use_variants: bool = True
    media_fingerprinting_use_yandex_download: bool = False
    media_fingerprinting_external_ai_enabled: bool = False
    media_similarity_dedup_enabled: bool = True
    media_similarity_exact_hash_threshold: float = 1.0
    media_similarity_near_hash_distance: int = 6
    media_similarity_tag_weight: float = 0.2
    media_similarity_visual_weight: float = 0.8
    media_duplicate_cluster_min_score: float = 0.82
    media_duplicate_auto_hide_enabled: bool = False
    media_duplicate_auto_delete_enabled: bool = False

    # --- Платежи (Россия). РЕАЛЬНЫЕ ПЛАТЕЖИ ВЫКЛЮЧЕНЫ по умолчанию ---
    # Без payments_live_enabled=true все счета создаются как mock/sandbox; баланс
    # пополняется только после статуса paid (mock-pay/webhook). Секреты провайдеров
    # читаются из окружения, в код не хардкодятся, в UI показываются только маской.
    payments_live_enabled: bool = False
    payments_default_provider: str = "mock"
    payments_success_return_url: str = ""
    payments_fail_return_url: str = ""
    # Реальные сетевые вызовы к платёжным API (эквайринг). По умолчанию ВЫКЛЮЧЕНО:
    # даже с sandbox-флагом провайдер не ходит в сеть, а строит детерминированный
    # fake-invoice/payload. Включать только после аудита sandbox/подписей вебхуков.
    payments_provider_http_enabled: bool = False
    # YooKassa
    yookassa_sandbox_enabled: bool = False
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    yookassa_webhook_secret: str = ""
    yookassa_return_url: str = ""
    yookassa_confirmation_type: str = "redirect"
    # T-Bank / Тинькофф
    tbank_sandbox_enabled: bool = False
    tbank_terminal_key: str = ""
    tbank_password: str = ""
    # CloudPayments
    cloudpayments_sandbox_enabled: bool = False
    cloudpayments_public_id: str = ""
    cloudpayments_api_secret: str = ""
    # Robokassa
    robokassa_sandbox_enabled: bool = False
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

    # --- Media Proxy: временные публичные HTTPS-ссылки на медиа (для Instagram) ---
    # Instagram Graph API публикует по публичному image_url, а не по локальному файлу.
    # Botfleet отдаёт медиа по временной ссылке https://<base>/media/public/{token}:
    # токен случайный/длинный, хранится только хеш, ссылка ограничена по времени и
    # отзывается. Base URL берётся из MEDIA_PROXY_PUBLIC_BASE_URL или PUBLIC_APP_URL/
    # APP_BASE_URL. В production обязателен HTTPS. Живая публикация Instagram выключена.
    media_proxy_enabled: bool = True
    media_proxy_public_base_url: str = ""
    media_proxy_default_ttl_seconds: int = 86400
    media_proxy_max_ttl_seconds: int = 604800
    media_proxy_max_bytes: int = 15728640
    media_proxy_allowed_content_types: str = "image/jpeg,image/png,image/webp"
    media_proxy_require_https_in_production: bool = True
    media_proxy_token_bytes: int = 32
    media_proxy_cache_dir: str = "tmp/media_proxy_cache"
    media_proxy_cache_enabled: bool = True

    # --- Background scheduler worker (движок автоматизации расписаний) ---
    # По умолчанию worker ВЫКЛЮЧЕН и в dry-run. Даже включённый worker НИКОГДА не делает
    # live-публикацию: только draft/needs_review. В production worker запускается ОТДЕЛЬНЫМ
    # процессом/контейнером (не внутри web-приложения). allowlist пустой = все доступные.
    scheduler_worker_enabled: bool = False
    scheduler_worker_interval_seconds: int = 60
    scheduler_worker_batch_size: int = 20
    scheduler_worker_dry_run: bool = True
    scheduler_worker_create_drafts: bool = True
    scheduler_worker_lock_ttl_seconds: int = 300
    scheduler_worker_max_projects_per_tick: int = 50
    scheduler_worker_platform_allowlist: str = ""
    scheduler_worker_account_allowlist: str = ""

    # --- Производные свойства (готовность к боевому запуску) ---

    @property
    def is_production(self) -> bool:
        """Запущено ли приложение в production-окружении."""
        return self.app_env.strip().lower() in {"production", "prod"}

    @property
    def is_local(self) -> bool:
        """Локальное/тестовое окружение."""
        return self.app_env.strip().lower() in {"local", "dev", "development", "test"}

    # --- Media Proxy: производные свойства ---

    @property
    def media_proxy_public_base_url_effective(self) -> str:
        """Базовый URL для публичных медиа-ссылок (без завершающего слэша).

        Приоритет: MEDIA_PROXY_PUBLIC_BASE_URL → PUBLIC_APP_URL → APP_BASE_URL.
        """
        for candidate in (
            self.media_proxy_public_base_url,
            self.public_app_url,
            self.app_base_url,
        ):
            if candidate and candidate.strip():
                return candidate.strip().rstrip("/")
        return ""

    @property
    def media_proxy_https_ready(self) -> bool:
        """Готов ли публичный base URL для внешних платформ (HTTPS и не localhost)."""
        base = self.media_proxy_public_base_url_effective.lower()
        if not base.startswith("https://"):
            return False
        return "127.0.0.1" not in base and "localhost" not in base

    @property
    def media_proxy_enabled_effective(self) -> bool:
        """Включён ли media-proxy и задан ли базовый URL для ссылок."""
        return self.media_proxy_enabled and bool(self.media_proxy_public_base_url_effective)

    @property
    def media_proxy_allowed_content_types_list(self) -> list[str]:
        """Разрешённые content-type для публичных медиа-ссылок."""
        return [
            ct.strip().lower()
            for ct in self.media_proxy_allowed_content_types.split(",")
            if ct.strip()
        ]

    # --- Background scheduler worker: производные свойства ---

    @property
    def scheduler_worker_enabled_effective(self) -> bool:
        """Включён ли фоновый worker (по умолчанию false)."""
        return bool(self.scheduler_worker_enabled)

    @property
    def scheduler_worker_interval_seconds_safe(self) -> int:
        """Интервал тика в безопасных границах [10, 3600] секунд."""
        return max(10, min(int(self.scheduler_worker_interval_seconds or 60), 3600))

    @property
    def scheduler_worker_platform_allowlist_list(self) -> list[str]:
        """Allowlist платформ (пусто = все доступные)."""
        return [
            p.strip().lower()
            for p in self.scheduler_worker_platform_allowlist.split(",")
            if p.strip()
        ]

    @property
    def scheduler_worker_account_allowlist_list(self) -> list[int]:
        """Allowlist account_id (пусто = все доступные)."""
        out: list[int] = []
        for raw in self.scheduler_worker_account_allowlist.split(","):
            raw = raw.strip()
            if raw.isdigit():
                out.append(int(raw))
        return out

    # --- Предложения экспериментов: производные свойства (v0.4.3) ---

    @property
    def experiment_suggestions_enabled_effective(self) -> bool:
        """Доступны ли предложения экспериментов (UI/API)."""
        return bool(self.experiment_suggestions_enabled)

    @property
    def experiment_suggestions_worker_enabled_effective(self) -> bool:
        """Может ли worker генерировать предложения (по умолчанию false)."""
        return bool(
            self.experiment_suggestions_enabled and self.experiment_suggestions_worker_enabled
        )

    @property
    def experiment_suggestions_auto_create_effective(self) -> bool:
        """Разрешено ли worker-у авто-создавать A/B из предложений (по умолчанию false).

        Даже при true эксперименты — только draft/needs_review; live-публикаций нет.
        """
        return bool(
            self.experiment_suggestions_enabled
            and self.experiment_suggestions_worker_enabled
            and self.experiment_suggestions_auto_create
        )

    @property
    def experiment_suggestions_cooldown_seconds(self) -> int:
        """Окно cooldown дедупа предложений (в секундах, безопасные границы)."""
        return max(0, int(self.experiment_suggestions_cooldown_hours or 0)) * 3600

    @property
    def experiment_suggestions_expire_seconds(self) -> int:
        """Срок жизни предложения (в секундах)."""
        return max(0, int(self.experiment_suggestions_expire_days or 0)) * 86400

    # --- Автовыбор темы: производные свойства (v0.4.4) ---

    @property
    def auto_topic_selection_enabled_effective(self) -> bool:
        """Доступен ли автовыбор тем (preview/UI/API/CLI)."""
        return bool(self.auto_topic_selection_enabled)

    @property
    def auto_topic_selection_worker_enabled_effective(self) -> bool:
        """Может ли worker сам создавать решения о теме (по умолчанию false).

        Даже при true пост создаётся только как draft/needs_review; live-публикаций нет.
        """
        return bool(self.auto_topic_selection_enabled and self.auto_topic_selection_worker_enabled)

    @property
    def auto_topic_selection_dry_run_effective(self) -> bool:
        """Dry-run автовыбора (по умолчанию true — без записи решений)."""
        return bool(self.auto_topic_selection_dry_run)

    @property
    def auto_topic_selection_min_confidence_safe(self) -> float:
        """Порог уверенности решения в безопасных границах [0..1]."""
        return max(0.0, min(1.0, float(self.auto_topic_selection_min_confidence or 0.0)))

    @property
    def auto_topic_selection_recency_days_safe(self) -> int:
        """Окно «недавних» постов для новизны (не отрицательное)."""
        return max(1, int(self.auto_topic_selection_recency_days or 1))

    @property
    def auto_topic_selection_fatigue_window_days_safe(self) -> int:
        """Окно усталости тем (не отрицательное)."""
        return max(1, int(self.auto_topic_selection_fatigue_window_days or 1))

    # --- Автовыбор медиа: производные свойства (v0.4.5) ---

    @property
    def auto_media_selection_enabled_effective(self) -> bool:
        """Доступен ли автовыбор медиа (preview/UI/API/CLI)."""
        return bool(self.auto_media_selection_enabled)

    @property
    def auto_media_selection_worker_enabled_effective(self) -> bool:
        """Может ли worker сам создавать решения о медиа (по умолчанию false).

        Даже при true пост создаётся только как draft/needs_review; live-публикаций нет;
        публичные ссылки автоматически НЕ создаются.
        """
        return bool(self.auto_media_selection_enabled and self.auto_media_selection_worker_enabled)

    @property
    def auto_media_selection_dry_run_effective(self) -> bool:
        """Dry-run автовыбора медиа (по умолчанию true — без записи решений)."""
        return bool(self.auto_media_selection_dry_run)

    @property
    def auto_media_selection_min_confidence_safe(self) -> float:
        """Порог уверенности медиа-решения в безопасных границах [0..1]."""
        return max(0.0, min(1.0, float(self.auto_media_selection_min_confidence or 0.0)))

    @property
    def auto_media_selection_recency_days_safe(self) -> int:
        """Окно «недавних» постов для новизны медиа (не отрицательное)."""
        return max(1, int(self.auto_media_selection_recency_days or 1))

    @property
    def auto_media_selection_fatigue_window_days_safe(self) -> int:
        """Окно усталости медиа (не отрицательное)."""
        return max(1, int(self.auto_media_selection_fatigue_window_days or 1))

    def auto_media_selection_max_images_for_platform(self, platform: str | None) -> int:
        """Максимум изображений в группе для платформы (безопасные границы)."""
        mapping = {
            "telegram": self.auto_media_selection_max_images_telegram,
            "vk": self.auto_media_selection_max_images_vk,
            "instagram": self.auto_media_selection_max_images_instagram,
        }
        return max(1, int(mapping.get(str(platform or "").lower(), 1) or 1))

    # --- Оценка качества медиа: производные свойства (v0.4.6) ---

    @property
    def media_quality_scoring_enabled_effective(self) -> bool:
        """Доступна ли оценка качества медиа (preview/UI/API/CLI)."""
        return bool(self.media_quality_scoring_enabled)

    @property
    def media_quality_scoring_worker_enabled_effective(self) -> bool:
        """Может ли worker сам писать снимки качества (по умолчанию false).

        Даже при true — правило-ориентированная оценка, без внешнего AI и без live-публикаций.
        """
        return bool(
            self.media_quality_scoring_enabled and self.media_quality_scoring_worker_enabled
        )

    @property
    def media_quality_scoring_dry_run_effective(self) -> bool:
        """Dry-run оценки качества (по умолчанию true — без записи снимков)."""
        return bool(self.media_quality_scoring_dry_run)

    @property
    def media_quality_min_good_score_safe(self) -> int:
        """Порог «good» в безопасных границах [0..100]."""
        return max(0, min(100, int(self.media_quality_min_good_score or 0)))

    @property
    def media_quality_min_excellent_score_safe(self) -> int:
        """Порог «excellent» в безопасных границах [good..100]."""
        good = self.media_quality_min_good_score_safe
        return max(good, min(100, int(self.media_quality_min_excellent_score or 0)))

    @property
    def media_quality_recency_days_safe(self) -> int:
        """Окно «недавних» постов для свежести медиа (не отрицательное)."""
        return max(1, int(self.media_quality_recency_days or 1))

    @property
    def media_quality_fatigue_window_days_safe(self) -> int:
        """Окно усталости медиа (не отрицательное)."""
        return max(1, int(self.media_quality_fatigue_window_days or 1))

    # --- Fingerprint/дедупликация медиа: производные свойства (v0.4.7) ---

    @property
    def media_fingerprinting_enabled_effective(self) -> bool:
        """Доступен ли fingerprint медиа (preview/UI/API/CLI)."""
        return bool(self.media_fingerprinting_enabled)

    @property
    def media_fingerprinting_worker_enabled_effective(self) -> bool:
        """Может ли worker сам считать fingerprint/кластеры (по умолчанию false).

        Даже при true — локальные хэши, без внешнего AI, без сети по умолчанию, без удаления.
        """
        return bool(self.media_fingerprinting_enabled and self.media_fingerprinting_worker_enabled)

    @property
    def media_fingerprinting_dry_run_effective(self) -> bool:
        """Dry-run fingerprint (по умолчанию true — без записи)."""
        return bool(self.media_fingerprinting_dry_run)

    @property
    def media_fingerprinting_max_assets_per_run_safe(self) -> int:
        """Максимум ассетов за один прогон fingerprint (не отрицательное)."""
        return max(1, int(self.media_fingerprinting_max_assets_per_run or 1))

    @property
    def media_similarity_near_hash_distance_safe(self) -> int:
        """Порог hamming-дистанции для «похожих» (безопасные границы [1..32])."""
        return max(1, min(32, int(self.media_similarity_near_hash_distance or 1)))

    @property
    def media_duplicate_cluster_min_score_safe(self) -> float:
        """Минимальный similarity для кластера дублей в границах [0..1]."""
        return max(0.0, min(1.0, float(self.media_duplicate_cluster_min_score or 0.0)))

    # --- Auth / session: производные (effective) свойства ---

    @property
    def auth_token_secret_effective(self) -> str:
        """Секрет подписи auth-токенов: из конфига или dev-фолбэк (вне production)."""
        configured = self.auth_token_secret.strip()
        return configured or DEV_AUTH_SECRET_FALLBACK

    @property
    def auth_token_secret_configured(self) -> bool:
        """Задан ли надёжный AUTH_TOKEN_SECRET (не пустой/не слабый дефолт, ≥16 симв.)."""
        s = self.auth_token_secret.strip()
        return bool(s) and s.lower() not in _KNOWN_WEAK_SECRETS and len(s) >= 16

    @property
    def auth_allow_dev_token_effective(self) -> bool:
        """Разрешён ли dev-токен: только вне production и при auth_allow_dev_token."""
        return self.auth_allow_dev_token and not self.is_production

    @property
    def auth_require_auth_effective(self) -> bool:
        """Требовать ли авторизацию на защищённых роутах (prod — всегда)."""
        return self.is_production or self.security_require_auth or self.auth_require_auth

    @property
    def csrf_enabled_effective(self) -> bool:
        """Включена ли CSRF-защита (в production — всегда)."""
        return self.csrf_protection_enabled or self.is_production

    @property
    def rate_limit_enabled_effective(self) -> bool:
        """Включён ли rate limiting (в production — всегда)."""
        return self.rate_limit_enabled or self.is_production

    @property
    def secure_cookies_effective(self) -> bool:
        """Ставить ли Secure-флаг на cookie (в production — всегда)."""
        return self.auth_cookie_secure or self.is_production

    @property
    def database_is_sqlite(self) -> bool:
        """Использует ли БД SQLite (для prod ожидается PostgreSQL)."""
        return self.database_url.strip().lower().startswith("sqlite")

    def payment_provider_sandbox_enabled(self, provider: str) -> bool:
        """Включён ли sandbox-режим у провайдера (можно создавать fake-счета без сети)."""
        return {
            "yookassa": self.yookassa_sandbox_enabled,
            "tbank": self.tbank_sandbox_enabled,
            "cloudpayments": self.cloudpayments_sandbox_enabled,
            "robokassa": self.robokassa_sandbox_enabled,
        }.get((provider or "").strip().lower(), False)

    @property
    def yookassa_return_url_effective(self) -> str:
        """Return URL для YooKassa: из настройки, из PAYMENTS_SUCCESS_RETURN_URL или базы."""
        for candidate in (
            self.yookassa_return_url,
            self.payments_success_return_url,
            (f"{self.app_base_url.rstrip('/')}/ui/billing" if self.app_base_url else ""),
        ):
            if candidate.strip():
                return candidate.strip()
        return "/ui/billing"

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


@dataclass(frozen=True)
class SecurityCheck:
    """Один пункт security-чек-листа готовности к production."""

    key: str
    ok: bool
    severity: str  # info (пройден) | warning | error
    message: str


def _payments_ok(settings: Settings) -> bool:
    """Платежи безопасны: либо live выключен, либо задан секрет провайдера."""
    if not settings.payments_live_enabled:
        return True
    return bool(
        settings.yookassa_secret_key or settings.tbank_password or settings.cloudpayments_api_secret
    )


def _live_publishing_off(settings: Settings) -> bool:
    """Все live-публикации выключены (allowlist пока не реализован)."""
    return not (
        settings.telegram_live_publishing_enabled
        or settings.vk_live_publishing_enabled
        or settings.instagram_live_publishing_enabled
        or settings.youtube_live_publishing_enabled
        or settings.rutube_live_publishing_enabled
    )


def _mk(key: str, ok: bool, prod_critical: bool, settings: Settings, message: str) -> SecurityCheck:
    """Собрать check: провал критичного пункта в production → error, иначе warning."""
    if ok:
        severity = "info"
    elif prod_critical and settings.is_production:
        severity = "error"
    else:
        severity = "warning"
    return SecurityCheck(key=key, ok=ok, severity=severity, message=message)


def security_checks(settings: Settings) -> list[SecurityCheck]:
    """Единый security-чек-лист (для /health/security-readiness и production_check CLI)."""
    return [
        _mk(
            "auth_secret_configured",
            settings.auth_token_secret_configured,
            True,
            settings,
            "AUTH_TOKEN_SECRET задан и надёжен (≥16 символов, не дефолт)",
        ),
        _mk(
            "dev_token_disabled",
            not settings.auth_allow_dev_token,
            True,
            settings,
            "AUTH_ALLOW_DEV_TOKEN=false (dev-токен запрещён)",
        ),
        _mk(
            "auth_required",
            settings.auth_require_auth,
            True,
            settings,
            "AUTH_REQUIRE_AUTH=true (авторизация обязательна)",
        ),
        _mk(
            "secure_cookies",
            settings.auth_cookie_secure,
            True,
            settings,
            "AUTH_COOKIE_SECURE=true (HTTPS-only cookie)",
        ),
        _mk(
            "csrf_enabled",
            settings.csrf_protection_enabled,
            True,
            settings,
            "CSRF_PROTECTION_ENABLED=true",
        ),
        _mk(
            "rate_limit_enabled",
            settings.rate_limit_enabled,
            True,
            settings,
            "RATE_LIMIT_ENABLED=true",
        ),
        _mk(
            "security_headers_enabled",
            settings.security_headers_enabled,
            True,
            settings,
            "SECURITY_HEADERS_ENABLED=true (CSP/HSTS/nosniff)",
        ),
        _mk(
            "database_not_sqlite",
            not settings.database_is_sqlite,
            True,
            settings,
            "DATABASE_URL — PostgreSQL (не SQLite)",
        ),
        _mk(
            "payments_live_disabled_or_configured",
            _payments_ok(settings),
            True,
            settings,
            "PAYMENTS_LIVE_ENABLED=false или задан секрет провайдера",
        ),
        _mk(
            "live_publishing_disabled",
            _live_publishing_off(settings),
            True,
            settings,
            "Live-публикации выключены (включаются только после отдельных тестов)",
        ),
        _mk(
            "audit_enabled",
            settings.audit_log_enabled,
            False,
            settings,
            "AUDIT_LOG_ENABLED=true (аудит действий)",
        ),
        _mk(
            "paid_actions_enforced",
            settings.paid_actions_enforced,
            False,
            settings,
            "PAID_ACTIONS_ENFORCED=true (платные действия требуют баланс)",
        ),
    ]


def production_security_errors(settings: Settings) -> list[str]:
    """Фатальные ошибки безопасности для production (пусто вне production).

    Используется на старте приложения (падение) и в ``/health/security-readiness``
    (503). Вне production всегда пусто — локальная разработка не блокируется.
    """
    return [c.message for c in security_checks(settings) if c.severity == "error"]


def production_security_warnings(settings: Settings) -> list[str]:
    """Некритичные предупреждения безопасности (для readiness в любом окружении)."""
    return [c.message for c in security_checks(settings) if c.severity == "warning"]


def validate_production_settings(settings: Settings | None = None) -> list[str]:
    """Вернуть фатальные production-ошибки конфигурации (алиас для CLI/старта)."""
    return production_security_errors(settings if settings is not None else get_settings())


def production_ready(settings: Settings) -> bool:
    """True, если нет фатальных production-ошибок конфигурации."""
    return not production_security_errors(settings)


@lru_cache
def get_settings() -> Settings:
    """Вернуть кешированный экземпляр настроек."""
    return Settings()
