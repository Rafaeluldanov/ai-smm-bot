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

    # --- Курирование медиатеки (v0.4.8) ---
    # Задачи очистки/разметки медиатеки (дубли, ретегинг, слабые медиа). Теги применяются
    # ТОЛЬКО после подтверждения клиента; файлы НЕ удаляются; внешнего AI нет. Курирование
    # worker-ом ВЫКЛЮЧЕНО по умолчанию; dry-run; авто-применение/скрытие/удаление выключены.
    media_curation_enabled: bool = True
    media_curation_worker_enabled: bool = False
    media_curation_dry_run: bool = True
    media_curation_auto_apply_tags: bool = False
    media_curation_auto_hide_duplicates: bool = False
    media_curation_auto_delete_enabled: bool = False
    media_curation_max_tasks_per_run: int = 100
    media_curation_min_confidence: float = 0.55
    media_curation_task_expire_days: int = 30
    media_curation_use_fingerprints: bool = True
    media_curation_use_quality: bool = True
    media_curation_use_learning: bool = True
    media_curation_external_ai_enabled: bool = False

    # --- Collaborative media curation review (v0.4.9) ---
    # Ревью медиатеки: задачи на проверку, ответственные, комментарии, история решений.
    # Изменения применяются ТОЛЬКО после approved; авто-применение и уведомления выключены;
    # внешнего AI нет; файлы не удаляются; live-публикаций/платежей не подразумевает.
    media_curation_review_enabled: bool = True
    media_curation_review_require_approval: bool = True
    media_curation_review_allow_self_approval: bool = True
    media_curation_review_default_priority: str = "normal"
    media_curation_review_overdue_days: int = 7
    media_curation_review_max_comments_per_task: int = 100
    media_curation_review_notify_enabled: bool = False
    media_curation_review_auto_apply_after_approval: bool = False
    media_curation_review_external_ai_enabled: bool = False

    # --- Notifications, mentions, reviewer workload (v0.5.0) ---
    # Внутренние (in-app) уведомления, упоминания и нагрузка ревьюеров. Внешняя доставка
    # (email/digest/webhook/push) ВЫКЛЮЧЕНА по умолчанию и в MVP не отправляется; worker
    # выключен; dry-run по умолчанию; live-публикаций/платежей не подразумевает.
    notifications_enabled: bool = True
    notifications_in_app_enabled: bool = True
    notifications_email_enabled: bool = False
    notifications_digest_enabled: bool = False
    notifications_webhook_enabled: bool = False
    notifications_worker_enabled: bool = False
    notifications_dry_run: bool = True
    notifications_max_per_user: int = 500
    notifications_dedup_window_minutes: int = 30
    notifications_mention_enabled: bool = True
    notifications_overdue_scan_enabled: bool = True
    notifications_overdue_grace_hours: int = 24
    notifications_external_delivery_enabled: bool = False
    media_curation_review_sla_hours: int = 72
    post_review_sla_hours: int = 48
    experiment_review_sla_hours: int = 72

    # --- Notification delivery sandbox: email/telegram/webhook + digest (v0.5.1) ---
    # Внешняя доставка уведомлений как sandbox/mock: провайдеры по умолчанию mock и НИЧЕГО не
    # отправляют. РЕАЛЬНАЯ доставка (SMTP/Telegram/webhook) ВЫКЛЮЧЕНА по умолчанию — все
    # *_LIVE_ENABLED и NOTIFICATION_EXTERNAL_DELIVERY_ENABLED = false; dry-run по умолчанию.
    notification_delivery_enabled: bool = True
    notification_delivery_dry_run: bool = True
    notification_external_delivery_enabled: bool = False

    notification_email_enabled: bool = False
    notification_email_provider: str = "mock"
    notification_email_live_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_tls: bool = True

    notification_telegram_enabled: bool = False
    notification_telegram_provider: str = "mock"
    notification_telegram_live_enabled: bool = False
    notification_telegram_bot_token: str = ""
    notification_telegram_default_chat_id: str = ""

    # --- Telegram notification templates + chat binding (v0.5.4) ---
    # Foundation Telegram-канала уведомлений: шаблоны, chat binding, live-ready adapter. РЕАЛЬНАЯ
    # Telegram-доставка ВЫКЛЮЧЕНА по умолчанию (live send false, test send false, dry-run true) и
    # требует ещё external+telegram live-флаги + verified binding. Bot token — только в env.
    notification_telegram_templates_enabled: bool = True
    notification_telegram_binding_enabled: bool = True
    notification_telegram_binding_token_bytes: int = 24
    notification_telegram_binding_token_ttl_days: int = 30
    notification_telegram_parse_mode: str = "none"
    notification_telegram_test_send_enabled: bool = False
    notification_telegram_test_send_dry_run: bool = True
    notification_telegram_max_message_chars: int = 3900
    notification_telegram_live_send_enabled: bool = False
    notification_telegram_require_verified_binding: bool = True
    notification_telegram_allow_unverified_test: bool = False

    # --- Telegram bot webhook/polling sandbox (v0.5.5) ---
    # Incoming webhook endpoint включён для local/sandbox; РЕАЛЬНЫЕ Telegram API-вызовы
    # (setWebhook/getUpdates/deleteWebhook) ВЫКЛЮЧЕНЫ по умолчанию (live false, dry-run true) и
    # требуют external+live-флаги + bot token. Secret token / bot token — только в env.
    notification_telegram_webhook_enabled: bool = True
    notification_telegram_webhook_live_enabled: bool = False
    notification_telegram_webhook_secret_required: bool = False
    notification_telegram_webhook_secret_token: str = ""
    notification_telegram_webhook_public_url: str = ""
    notification_telegram_webhook_path: str = "/notification-telegram/webhook"
    notification_telegram_webhook_allow_local_without_secret: bool = True
    notification_telegram_polling_enabled: bool = True
    notification_telegram_polling_live_enabled: bool = False
    notification_telegram_polling_dry_run: bool = True
    notification_telegram_polling_limit: int = 20
    notification_telegram_webhook_management_enabled: bool = True
    notification_telegram_webhook_management_live_enabled: bool = False
    notification_telegram_webhook_management_dry_run: bool = True
    notification_telegram_incoming_update_log_enabled: bool = True
    notification_telegram_incoming_max_text_preview: int = 200

    # --- Autopilot-first client workspace (v0.5.6) ---
    # Простой клиентский workspace: клиент подключает площадки, даёт Яндекс Диск, выбирает
    # календарь и включает автопилот. full_auto — основной режим продукта, но он НЕ включает
    # глобальные live-флаги публикации и НЕ обходит существующие safety-gates. health worker
    # выключен; auto-start live выключен; advanced-настройки скрыты по умолчанию.
    autopilot_ui_enabled: bool = True
    autopilot_default_mode: str = "full_auto"
    autopilot_full_auto_primary: bool = True
    autopilot_semi_auto_secondary: bool = True
    autopilot_require_yandex_disk: bool = True
    autopilot_require_calendar: bool = True
    autopilot_require_platform: bool = True
    autopilot_health_check_enabled: bool = True
    autopilot_health_check_worker_enabled: bool = False
    autopilot_health_check_dry_run: bool = True
    autopilot_auto_create_schedules: bool = True
    autopilot_auto_start_live: bool = False
    autopilot_show_advanced_settings: bool = False
    autopilot_min_media_assets: int = 5
    autopilot_recommended_media_assets: int = 30
    autopilot_default_posts_per_day: int = 1
    autopilot_default_publish_time: str = "10:00"
    autopilot_default_timezone: str = "Europe/Moscow"

    # --- Yandex Disk auto-sync worker (v0.5.7) ---
    # Клиент загружает картинки в Яндекс Диск — Botfleet сам синхронизирует медиатеку для
    # автопостинга. РЕАЛЬНАЯ сеть/worker ВЫКЛЮЧЕНЫ по умолчанию (dry-run true, network false),
    # файлы НЕ удаляются/не скрываются. Public URL — публичная ссылка, не секрет.
    yandex_auto_sync_enabled: bool = True
    yandex_auto_sync_worker_enabled: bool = False
    yandex_auto_sync_dry_run: bool = True
    yandex_auto_sync_network_enabled: bool = False
    yandex_auto_sync_public_url_enabled: bool = True
    yandex_auto_sync_oauth_enabled: bool = False
    yandex_auto_sync_default_frequency_minutes: int = 60
    yandex_auto_sync_max_projects_per_tick: int = 20
    yandex_auto_sync_max_files_per_run: int = 500
    yandex_auto_sync_min_media_assets: int = 5
    yandex_auto_sync_recommended_media_assets: int = 30
    yandex_auto_sync_run_quality_scoring: bool = True
    yandex_auto_sync_run_fingerprinting: bool = True
    yandex_auto_sync_run_curation_preview: bool = True
    yandex_auto_sync_auto_delete: bool = False
    yandex_auto_sync_auto_hide: bool = False

    # --- Autopilot Calendar Assistant (v0.5.8) ---
    # Клиент выбирает цель и частоту — Botfleet строит календарь автопостинга. Применение
    # календаря создаёт/обновляет CrmPublishingPlan, но НЕ публикует и НЕ включает live-флаги.
    autopilot_calendar_assistant_enabled: bool = True
    autopilot_calendar_assistant_dry_run: bool = True
    autopilot_calendar_auto_apply_enabled: bool = True
    autopilot_calendar_default_preset: str = "three_per_week"
    autopilot_calendar_default_goal: str = "mixed"
    autopilot_calendar_default_timezone: str = "Europe/Moscow"
    autopilot_calendar_default_time: str = "10:00"
    autopilot_calendar_max_posts_per_day: int = 3
    autopilot_calendar_max_platforms: int = 5
    autopilot_calendar_min_media_per_month: int = 10
    autopilot_calendar_require_media: bool = True
    autopilot_calendar_require_platform: bool = True
    autopilot_calendar_use_learning_best_times: bool = True
    autopilot_calendar_use_balance_estimate: bool = True
    autopilot_calendar_live_start_enabled: bool = False

    # --- Live autopost readiness audit (v0.5.9) ---
    # Готовность проекта/площадок к РЕАЛЬНОЙ автопубликации. Эти флаги НЕ включают live-публикацию:
    # реальная публикация по-прежнему требует глобальных *_LIVE_PUBLISHING_ENABLED. Per-project/
    # per-platform switch НЕ обходит глобальные флаги. Внешние probe и авто-включение — выключены.
    live_readiness_enabled: bool = True
    live_readiness_dry_run: bool = True
    live_readiness_worker_enabled: bool = False
    live_readiness_require_confirmation: bool = True
    live_readiness_require_project_confirmation: bool = True

    # AI Learning Loop (v0.6.5). Слой памяти/обучения per-client. Обучение НЕ публикует,
    # НЕ включает и НЕ обходит глобальные *_LIVE_PUBLISHING_ENABLED и НЕ меняет стратегию
    # автоматически. `auto_apply_strategy` по умолчанию ВЫКЛЮЧЕН (только рекомендации).
    ai_learning_enabled: bool = True
    ai_learning_auto_apply_strategy_enabled: bool = False
    ai_learning_default_window_days: int = 90
    ai_learning_min_events_for_stable: int = 20

    # Autonomous Content Strategist (v0.6.6). Слой РЕКОМЕНДАЦИЙ. НЕ включает live, НЕ
    # публикует, НЕ меняет активный календарь сам. `auto_apply` по умолчанию ВЫКЛЮЧЕН:
    # изменения только через Recommendation → Review → Apply с подтверждением.
    content_strategy_enabled: bool = True
    content_strategy_auto_apply_enabled: bool = False

    # AI Campaign Manager (v0.6.7). Слой планирования/рекомендаций кампаний. НЕ публикует,
    # НЕ включает live, НЕ меняет активный календарь сам. `auto_apply` по умолчанию ВЫКЛЮЧЕН:
    # изменения только через Approve → Apply (с подтверждением APPLY_CAMPAIGN).
    ai_campaign_enabled: bool = True
    ai_campaign_auto_apply_enabled: bool = False

    # AI Sales & Lead Intelligence (v0.6.8). Аналитический слой «контент → лид → выручка».
    # НЕ отправляет сообщения клиентам, НЕ меняет CRM, НЕ продаёт, НЕ включает live.
    sales_intelligence_enabled: bool = True
    sales_intelligence_default_attribution_model: str = "last_touch"

    # AI Business Growth Agent (v0.6.9). Advisory-слой роста бизнеса. НЕ меняет бизнес/CRM/
    # бюджет/live/публикации сам. `auto_apply` по умолчанию ВЫКЛЮЧЕН: изменения только через
    # Analyze → Recommend → Review → Apply (с подтверждением APPLY_GROWTH_ACTION).
    business_growth_enabled: bool = True
    business_growth_auto_apply_enabled: bool = False

    # Autonomous Business OS / AI Executive Layer (v0.7.0). Advisory + planning верхнего
    # уровня. НЕ меняет бизнес/CRM/бюджет/live/публикации сам. `auto_apply` по умолчанию
    # ВЫКЛЮЧЕН: изменения только через Approve → Apply (с подтверждением APPLY_BUSINESS_ACTION).
    business_os_enabled: bool = True
    business_os_auto_apply_enabled: bool = False

    # AI Chief of Staff / Executive Assistant Layer (v0.7.1). Персональный AI-ассистент
    # владельца: брифинги + задачи + память решений. Advisory + assistant — НЕ выполняет
    # задачи и НЕ меняет CRM/бюджет/продажи/live/публикации сам. Память лишь ДОБАВЛЯЕТ
    # контекст будущим рекомендациям.
    chief_of_staff_enabled: bool = True

    live_readiness_require_platform_confirmation: bool = True
    live_readiness_min_score_to_enable: int = 85
    live_readiness_allow_global_flag_override: bool = False
    live_readiness_auto_enable: bool = False
    live_readiness_probe_external_api: bool = False
    live_readiness_notify_on_blockers: bool = True
    live_readiness_check_balance: bool = True
    live_readiness_check_media: bool = True
    live_readiness_check_calendar: bool = True
    live_readiness_check_security: bool = True

    live_autopilot_enable_ui: bool = True
    live_autopilot_enable_api: bool = True
    live_autopilot_default_mode: str = "disabled"
    live_autopilot_confirmation_text: str = "ENABLE_LIVE_AUTOPILOT"
    live_platform_confirmation_text: str = "ENABLE_PLATFORM_LIVE"

    # --- Telegram-first live rollout (v0.6.0) ---
    # Первый реальный live-канал автопилота. Эти флаги НЕ включают live: реальная отправка требует
    # глобального TELEGRAM_LIVE_PUBLISHING_ENABLED + per-project/per-platform live + подтверждения.
    # allow_real_send=false по умолчанию — реальная отправка выключена даже при прочих условиях.
    telegram_live_rollout_enabled: bool = True
    telegram_live_rollout_dry_run: bool = True
    telegram_live_rollout_run_once_enabled: bool = True
    telegram_live_rollout_require_confirmation: bool = True
    telegram_live_rollout_confirmation_text: str = "ENABLE_TELEGRAM_LIVE"
    telegram_live_rollout_allow_real_send: bool = False
    telegram_live_rollout_require_readiness: bool = True
    telegram_live_rollout_require_full_auto: bool = True
    telegram_live_rollout_max_attempts_per_post: int = 1
    telegram_live_rollout_notify_on_blocked: bool = True
    telegram_live_rollout_notify_on_published: bool = True
    telegram_live_rollout_record_payload_preview: bool = True

    # --- Telegram live production runbook (v0.6.3) ---
    # Клиентский «запуск Telegram автопилота»: чек-лист + production-тест. Реальная отправка
    # делегируется TelegramLiveRolloutService (все гейты); runbook сам live не включает.
    telegram_runbook_enabled: bool = True
    telegram_runbook_dry_run: bool = True

    # --- Live autopilot monitoring & kill switch (v0.6.1) ---
    # Наблюдение за live/autopilot попытками, инциденты, kill switch. Kill switch управляет ТОЛЬКО
    # состоянием в БД (project/platform/autopilot) и НЕ трогает глобальные live-флаги. Worker и
    # авто-пауза выключены по умолчанию; dry-run true.
    live_autopilot_monitoring_enabled: bool = True
    live_autopilot_monitoring_dry_run: bool = True
    live_autopilot_monitoring_worker_enabled: bool = False
    live_autopilot_monitoring_window_hours: int = 24
    live_autopilot_monitoring_max_attempts_for_health: int = 100
    live_autopilot_monitoring_failure_warning_rate: float = 0.25
    live_autopilot_monitoring_failure_critical_rate: float = 0.50
    live_autopilot_incidents_enabled: bool = True
    live_autopilot_incident_dedup_hours: int = 24
    live_autopilot_auto_pause_enabled: bool = False
    live_autopilot_auto_pause_failures_threshold: int = 3
    live_autopilot_auto_pause_critical_only: bool = True
    live_autopilot_kill_switch_enabled: bool = True
    live_autopilot_kill_switch_require_confirmation: bool = True
    live_autopilot_pause_confirmation_text: str = "PAUSE_AUTOPILOT"
    live_autopilot_resume_confirmation_text: str = "RESUME_AUTOPILOT"

    notification_webhook_enabled: bool = False
    notification_webhook_provider: str = "mock"
    notification_webhook_live_enabled: bool = False
    notification_webhook_signing_secret: str = ""

    notification_digest_enabled: bool = False
    notification_digest_worker_enabled: bool = False
    notification_digest_dry_run: bool = True
    notification_digest_default_frequency: str = "daily"
    notification_digest_max_notifications: int = 50

    notification_delivery_retry_enabled: bool = True
    notification_delivery_max_attempts: int = 3
    notification_delivery_retry_backoff_seconds: int = 300

    # --- Notification safety: unsubscribe, rate limits, suppression, webhooks (v0.5.2) ---
    # Safety-слой ПЕРЕД реальной внешней доставкой: отписки, лимиты, подавление, подписанные
    # webhook. Реальная внешняя доставка/webhook по-прежнему ВЫКЛЮЧЕНЫ по умолчанию; секреты
    # webhook хранятся зашифрованно/masked и наружу не отдаются.
    notification_safety_enabled: bool = True
    notification_unsubscribe_enabled: bool = True
    notification_unsubscribe_token_secret: str = ""
    notification_unsubscribe_token_ttl_days: int = 365
    notification_rate_limit_enabled: bool = True
    notification_rate_limit_email_per_hour: int = 20
    notification_rate_limit_telegram_per_hour: int = 30
    notification_rate_limit_webhook_per_hour: int = 60
    notification_rate_limit_digest_per_day: int = 2
    notification_suppression_enabled: bool = True
    notification_suppression_failure_threshold: int = 5
    notification_suppression_ttl_hours: int = 24
    notification_webhook_subscriptions_enabled: bool = True
    notification_webhook_subscriptions_live_enabled: bool = False
    notification_webhook_signature_header: str = "X-Botfleet-Signature"
    notification_webhook_timestamp_header: str = "X-Botfleet-Timestamp"
    notification_webhook_max_payload_bytes: int = 262144

    # --- Email templates and SMTP sandbox/live-ready (v0.5.3) ---
    # Email-шаблоны + SMTP-adapter как live-ready foundation. РЕАЛЬНАЯ SMTP-отправка ВЫКЛЮЧЕНА по
    # умолчанию (SMTP_LIVE_SEND_ENABLED=false, SMTP_DRY_RUN=true) и требует ещё external+email
    # live-флаги. Тестовая отправка выключена; preview/sandbox доступны. Секреты — только в env.
    email_templates_enabled: bool = True
    email_template_overrides_enabled: bool = False
    email_template_preview_enabled: bool = True
    email_unsubscribe_footer_enabled: bool = True
    smtp_live_send_enabled: bool = False
    smtp_dry_run: bool = True
    smtp_timeout_seconds: int = 20
    smtp_max_recipients_per_message: int = 1
    smtp_require_tls: bool = True
    smtp_allow_self_signed: bool = False
    email_test_send_enabled: bool = False
    email_test_send_dry_run: bool = True
    email_test_allowed_recipients: str = ""

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
    # --- Media Proxy delivery layer (v0.6.2): домен, ресайз/трансформации, лимиты, кеш ---
    # MEDIA_PROXY_DOMAIN — публичный домен доставки (алиас/приоритет над public_base_url).
    # SECRET_KEY — необязательный «перец» для хеша токена (усиление, не замена случайного токена).
    # ENABLE_RESIZE — трансформации на лету; ALLOW_ORIGINAL — отдавать оригинал по токену.
    media_proxy_domain: str = ""
    media_proxy_secret_key: str = ""
    media_proxy_max_requests: int = 10000
    media_proxy_enable_resize: bool = True
    media_proxy_cache_seconds: int = 86400
    media_proxy_allow_original: bool = False

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
            self.media_proxy_domain,
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

    @property
    def media_proxy_resize_enabled_effective(self) -> bool:
        """Разрешены ли трансформации/ресайз на лету (v0.6.2)."""
        return bool(self.media_proxy_enabled and self.media_proxy_enable_resize)

    @property
    def media_proxy_allow_original_effective(self) -> bool:
        """Разрешено ли отдавать оригинал по токену (по умолчанию НЕТ — только трансформации)."""
        return bool(self.media_proxy_allow_original)

    @property
    def media_proxy_max_requests_safe(self) -> int:
        """Максимум запросов на токен (0 = без лимита; отрицательное → 0)."""
        return max(0, int(self.media_proxy_max_requests or 0))

    @property
    def media_proxy_cache_seconds_safe(self) -> int:
        """TTL кеша трансформаций в секундах (в границах 0..604800)."""
        return max(0, min(604800, int(self.media_proxy_cache_seconds or 0)))

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
    def business_os_enabled_effective(self) -> bool:
        """Доступен ли Autonomous Business OS (анализ/план/действия/UI/API)."""
        return bool(self.business_os_enabled)

    @property
    def business_os_auto_apply_enabled_effective(self) -> bool:
        """Может ли Executive Layer САМ применять действия (по умолчанию false — только approve)."""
        return bool(self.business_os_enabled and self.business_os_auto_apply_enabled)

    @property
    def chief_of_staff_enabled_effective(self) -> bool:
        """Доступен ли AI Chief of Staff (брифинги/задачи/память решений/UI/API)."""
        return bool(self.chief_of_staff_enabled)

    @property
    def business_growth_enabled_effective(self) -> bool:
        """Доступен ли AI Business Growth Agent (анализ/рекомендации/UI/API)."""
        return bool(self.business_growth_enabled)

    @property
    def business_growth_auto_apply_enabled_effective(self) -> bool:
        """Может ли growth-агент САМ применять рекомендации (по умолчанию false — только review)."""
        return bool(self.business_growth_enabled and self.business_growth_auto_apply_enabled)

    @property
    def sales_intelligence_enabled_effective(self) -> bool:
        """Доступен ли AI Sales & Lead Intelligence (анализ/атрибуция/UI/API)."""
        return bool(self.sales_intelligence_enabled)

    @property
    def sales_intelligence_default_attribution_model_safe(self) -> str:
        """Модель атрибуции по умолчанию в допустимых значениях."""
        model = str(self.sales_intelligence_default_attribution_model or "last_touch")
        return model if model in ("first_touch", "last_touch", "multi_touch") else "last_touch"

    @property
    def ai_campaign_enabled_effective(self) -> bool:
        """Доступен ли AI Campaign Manager (создание/план/рекомендации/UI/API)."""
        return bool(self.ai_campaign_enabled)

    @property
    def ai_campaign_auto_apply_enabled_effective(self) -> bool:
        """Может ли кампания САМА применяться (по умолчанию false — только Approve→Apply)."""
        return bool(self.ai_campaign_enabled and self.ai_campaign_auto_apply_enabled)

    @property
    def content_strategy_enabled_effective(self) -> bool:
        """Доступен ли автономный контент-стратег (анализ/рекомендации/UI/API)."""
        return bool(self.content_strategy_enabled)

    @property
    def content_strategy_auto_apply_enabled_effective(self) -> bool:
        """Может ли стратег САМ применять рекомендации (по умолчанию false — только review)."""
        return bool(self.content_strategy_enabled and self.content_strategy_auto_apply_enabled)

    @property
    def ai_learning_enabled_effective(self) -> bool:
        """Доступен ли AI Learning Loop (анализ/рекомендации/UI/API)."""
        return bool(self.ai_learning_enabled)

    @property
    def ai_learning_auto_apply_strategy_enabled_effective(self) -> bool:
        """Может ли обучение САМО применять стратегию (по умолчанию false — только рекомендации)."""
        return bool(self.ai_learning_enabled and self.ai_learning_auto_apply_strategy_enabled)

    @property
    def ai_learning_default_window_days_safe(self) -> int:
        """Окно анализа в безопасных границах [1..365]."""
        return max(1, min(365, int(self.ai_learning_default_window_days or 90)))

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

    # --- Курирование медиатеки: производные свойства (v0.4.8) ---

    @property
    def media_curation_enabled_effective(self) -> bool:
        """Доступно ли курирование медиатеки (preview/UI/API/CLI)."""
        return bool(self.media_curation_enabled)

    @property
    def media_curation_worker_enabled_effective(self) -> bool:
        """Может ли worker сам создавать задачи курирования (по умолчанию false).

        Даже при true теги применяются только после подтверждения; файлы не удаляются.
        """
        return bool(self.media_curation_enabled and self.media_curation_worker_enabled)

    @property
    def media_curation_dry_run_effective(self) -> bool:
        """Dry-run курирования (по умолчанию true — без записи задач)."""
        return bool(self.media_curation_dry_run)

    @property
    def media_curation_min_confidence_safe(self) -> float:
        """Порог уверенности задачи курирования в границах [0..1]."""
        return max(0.0, min(1.0, float(self.media_curation_min_confidence or 0.0)))

    @property
    def media_curation_max_tasks_per_run_safe(self) -> int:
        """Максимум задач за один прогон курирования (не отрицательное)."""
        return max(1, int(self.media_curation_max_tasks_per_run or 1))

    @property
    def media_curation_task_expire_seconds(self) -> int:
        """Срок жизни proposed-задачи в секундах (из дней; не отрицательное)."""
        return max(1, int(self.media_curation_task_expire_days or 1)) * 86400

    # --- Collaborative media curation review: производные свойства (v0.4.9) ---

    @property
    def media_curation_review_enabled_effective(self) -> bool:
        """Доступен ли workflow ревью медиатеки (нужно и общее курирование)."""
        return bool(self.media_curation_enabled and self.media_curation_review_enabled)

    @property
    def media_curation_review_require_approval_effective(self) -> bool:
        """Требуется ли approved перед apply (по умолчанию true).

        Если ревью выключено — гейт не действует (обратная совместимость с прямым apply).
        """
        return bool(
            self.media_curation_review_enabled_effective
            and self.media_curation_review_require_approval
        )

    @property
    def media_curation_review_default_priority_safe(self) -> str:
        """Приоритет задачи по умолчанию (валидное значение; иначе normal)."""
        value = str(self.media_curation_review_default_priority or "normal").strip().lower()
        return value if value in ("low", "normal", "high", "urgent") else "normal"

    @property
    def media_curation_review_overdue_seconds(self) -> int:
        """Порог просрочки задачи ревью в секундах (из дней; не отрицательное)."""
        return max(1, int(self.media_curation_review_overdue_days or 1)) * 86400

    @property
    def media_curation_review_max_comments_per_task_safe(self) -> int:
        """Максимум комментариев на задачу (не меньше 1)."""
        return max(1, int(self.media_curation_review_max_comments_per_task or 1))

    # --- Notifications: производные (effective) свойства (v0.5.0) ---

    @property
    def notifications_enabled_effective(self) -> bool:
        """Включены ли уведомления вообще."""
        return bool(self.notifications_enabled)

    @property
    def notifications_in_app_enabled_effective(self) -> bool:
        """Включён ли внутренний (in-app) канал уведомлений."""
        return bool(self.notifications_enabled and self.notifications_in_app_enabled)

    @property
    def notifications_external_delivery_enabled_effective(self) -> bool:
        """Разрешена ли ЛЮБАЯ внешняя доставка (email/digest/webhook). По умолчанию false.

        Требует и общий флаг внешней доставки, и хотя бы один внешний канал. В MVP всегда
        false — реальная отправка не производится.
        """
        return bool(
            self.notifications_external_delivery_enabled
            and (
                self.notifications_email_enabled
                or self.notifications_digest_enabled
                or self.notifications_webhook_enabled
            )
        )

    @property
    def notifications_dedup_window_seconds(self) -> int:
        """Окно дедупликации уведомлений в секундах (из минут; не отрицательное)."""
        return max(0, int(self.notifications_dedup_window_minutes or 0)) * 60

    @property
    def notifications_overdue_grace_seconds(self) -> int:
        """Грейс-период просрочки в секундах (из часов; не отрицательное)."""
        return max(0, int(self.notifications_overdue_grace_hours or 0)) * 3600

    @property
    def notifications_max_per_user_safe(self) -> int:
        """Максимум уведомлений на пользователя (не меньше 1)."""
        return max(1, int(self.notifications_max_per_user or 1))

    @property
    def media_curation_review_sla_seconds(self) -> int:
        """SLA ревью медиатеки в секундах (из часов; не отрицательное)."""
        return max(1, int(self.media_curation_review_sla_hours or 1)) * 3600

    @property
    def post_review_sla_seconds(self) -> int:
        """SLA ревью постов в секундах (из часов; не отрицательное)."""
        return max(1, int(self.post_review_sla_hours or 1)) * 3600

    @property
    def experiment_review_sla_seconds(self) -> int:
        """SLA ревью экспериментов в секундах (из часов; не отрицательное)."""
        return max(1, int(self.experiment_review_sla_hours or 1)) * 3600

    # --- Notification delivery: производные (effective) свойства (v0.5.1) ---

    @property
    def notification_delivery_enabled_effective(self) -> bool:
        """Доступна ли подсистема доставки (создание delivery-задач, логи, dry-run)."""
        return bool(self.notifications_enabled and self.notification_delivery_enabled)

    @property
    def notification_external_delivery_enabled_effective(self) -> bool:
        """Разрешена ли ЛЮБАЯ реальная внешняя доставка. По умолчанию false — в MVP отправки нет."""
        return bool(
            self.notification_delivery_enabled_effective
            and self.notification_external_delivery_enabled
        )

    def _channel_live_effective(self, enabled: bool, live: bool) -> bool:
        """Канал реально шлёт наружу только при external-флаге, включённом канале и его live."""
        return bool(self.notification_external_delivery_enabled_effective and enabled and live)

    @property
    def notification_email_enabled_effective(self) -> bool:
        """Реальная отправка email (по умолчанию false — используется mock)."""
        return self._channel_live_effective(
            self.notification_email_enabled, self.notification_email_live_enabled
        )

    @property
    def notification_telegram_enabled_effective(self) -> bool:
        """Реальная отправка Telegram-уведомлений (по умолчанию false — mock)."""
        return self._channel_live_effective(
            self.notification_telegram_enabled, self.notification_telegram_live_enabled
        )

    @property
    def notification_webhook_enabled_effective(self) -> bool:
        """Реальный вызов webhook (по умолчанию false — mock)."""
        return self._channel_live_effective(
            self.notification_webhook_enabled, self.notification_webhook_live_enabled
        )

    @property
    def notification_digest_enabled_effective(self) -> bool:
        """Доступны ли дайджесты (генерация/предпросмотр; по умолчанию false)."""
        return bool(
            self.notification_delivery_enabled_effective and self.notification_digest_enabled
        )

    @property
    def notification_digest_worker_enabled_effective(self) -> bool:
        """Может ли worker сам запускать дайджест-планировщик (по умолчанию false)."""
        return bool(
            self.notification_digest_enabled_effective and self.notification_digest_worker_enabled
        )

    @property
    def notification_delivery_max_attempts_safe(self) -> int:
        """Максимум попыток доставки (не меньше 1)."""
        return max(1, int(self.notification_delivery_max_attempts or 1))

    @property
    def notification_delivery_retry_backoff_seconds_safe(self) -> int:
        """Backoff между попытками в секундах (не отрицательное)."""
        return max(1, int(self.notification_delivery_retry_backoff_seconds or 1))

    @property
    def notification_digest_max_notifications_safe(self) -> int:
        """Максимум уведомлений в одном дайджесте (не меньше 1)."""
        return max(1, int(self.notification_digest_max_notifications or 1))

    @property
    def notification_digest_default_frequency_safe(self) -> str:
        """Частота дайджеста по умолчанию (daily|weekly; иначе daily)."""
        value = str(self.notification_digest_default_frequency or "daily").strip().lower()
        return value if value in ("daily", "weekly") else "daily"

    @property
    def smtp_configured(self) -> bool:
        """Заданы ли минимальные SMTP-параметры (host + from). Секрет не раскрывается."""
        return bool(self.smtp_host.strip() and self.smtp_from_email.strip())

    @property
    def notification_telegram_configured(self) -> bool:
        """Задан ли токен Telegram-бота (наличие, без раскрытия значения)."""
        return bool(self.notification_telegram_bot_token.strip())

    @property
    def notification_webhook_signing_configured(self) -> bool:
        """Задан ли секрет подписи webhook (наличие, без раскрытия значения)."""
        return bool(self.notification_webhook_signing_secret.strip())

    # --- Notification safety: производные (effective) свойства (v0.5.2) ---

    @property
    def notification_safety_enabled_effective(self) -> bool:
        """Включён ли safety-слой уведомлений (opt-out/лимиты/подавление/webhooks)."""
        return bool(self.notifications_enabled and self.notification_safety_enabled)

    @property
    def notification_unsubscribe_enabled_effective(self) -> bool:
        """Доступна ли отписка (opt-out) через токен."""
        return bool(
            self.notification_safety_enabled_effective and self.notification_unsubscribe_enabled
        )

    @property
    def notification_rate_limit_enabled_effective(self) -> bool:
        """Действуют ли лимиты доставки."""
        return bool(
            self.notification_safety_enabled_effective and self.notification_rate_limit_enabled
        )

    @property
    def notification_suppression_enabled_effective(self) -> bool:
        """Действует ли подавление доставки при ошибках."""
        return bool(
            self.notification_safety_enabled_effective and self.notification_suppression_enabled
        )

    @property
    def notification_webhook_subscriptions_enabled_effective(self) -> bool:
        """Доступны ли webhook-подписки (создание/preview; live-вызов — отдельно)."""
        return bool(
            self.notification_safety_enabled_effective
            and self.notification_webhook_subscriptions_enabled
        )

    @property
    def notification_webhook_subscriptions_live_enabled_effective(self) -> bool:
        """Разрешён ли РЕАЛЬНЫЙ вызов webhook. По умолчанию false — в MVP только mock preview."""
        return bool(
            self.notification_webhook_subscriptions_enabled_effective
            and self.notification_external_delivery_enabled_effective
            and self.notification_webhook_subscriptions_live_enabled
        )

    @property
    def notification_suppression_ttl_seconds(self) -> int:
        """TTL подавления в секундах (из часов; не отрицательное)."""
        return max(1, int(self.notification_suppression_ttl_hours or 1)) * 3600

    @property
    def notification_suppression_failure_threshold_safe(self) -> int:
        """Порог числа ошибок до подавления (не меньше 1)."""
        return max(1, int(self.notification_suppression_failure_threshold or 1))

    @property
    def notification_unsubscribe_token_ttl_seconds(self) -> int:
        """TTL токена отписки в секундах (из дней; не отрицательное)."""
        return max(1, int(self.notification_unsubscribe_token_ttl_days or 1)) * 86400

    @property
    def notification_unsubscribe_token_secret_effective(self) -> str:
        """Секрет подписи токена отписки: свой или (вне production) фолбэк на auth-секрет."""
        configured = self.notification_unsubscribe_token_secret.strip()
        if configured:
            return configured
        return self.auth_token_secret_effective

    # --- Email templates / SMTP: производные (effective) свойства (v0.5.3) ---

    @property
    def email_templates_enabled_effective(self) -> bool:
        """Доступны ли email-шаблоны (нужно и общее notifications-включение)."""
        return bool(self.notifications_enabled and self.email_templates_enabled)

    @property
    def email_template_preview_enabled_effective(self) -> bool:
        """Доступен ли preview email-шаблонов."""
        return bool(self.email_templates_enabled_effective and self.email_template_preview_enabled)

    @property
    def email_unsubscribe_footer_enabled_effective(self) -> bool:
        """Добавлять ли футер отписки в email (нужно и включённую отписку)."""
        return bool(
            self.email_templates_enabled_effective
            and self.email_unsubscribe_footer_enabled
            and self.notification_unsubscribe_enabled_effective
        )

    @property
    def smtp_dry_run_effective(self) -> bool:
        """Dry-run SMTP (по умолчанию true — реальной отправки нет)."""
        return bool(self.smtp_dry_run)

    @property
    def smtp_live_send_enabled_effective(self) -> bool:
        """Разрешена ли РЕАЛЬНАЯ SMTP-отправка. По умолчанию false — требует всех флагов.

        Нужны: внешняя доставка + email live + SMTP live + SMTP настроен + НЕ dry-run.
        """
        return bool(
            self.notification_email_enabled_effective
            and self.smtp_live_send_enabled
            and self.smtp_configured
            and not self.smtp_dry_run
        )

    @property
    def smtp_timeout_seconds_safe(self) -> int:
        """Таймаут SMTP в секундах (в границах 1..120)."""
        return max(1, min(120, int(self.smtp_timeout_seconds or 20)))

    @property
    def smtp_max_recipients_per_message_safe(self) -> int:
        """Максимум получателей на одно письмо (не меньше 1)."""
        return max(1, int(self.smtp_max_recipients_per_message or 1))

    @property
    def email_test_send_enabled_effective(self) -> bool:
        """Доступна ли тестовая отправка email (по умолчанию false)."""
        return bool(self.email_templates_enabled_effective and self.email_test_send_enabled)

    @property
    def email_test_allowed_recipients_list(self) -> list[str]:
        """Список разрешённых получателей тестовой отправки (из CSV)."""
        raw = str(self.email_test_allowed_recipients or "")
        return [x.strip().lower() for x in raw.split(",") if x.strip()]

    # --- Telegram notifications: производные (effective) свойства (v0.5.4) ---

    @property
    def notification_telegram_templates_enabled_effective(self) -> bool:
        """Доступны ли Telegram-шаблоны (нужно и общее notifications-включение)."""
        return bool(self.notifications_enabled and self.notification_telegram_templates_enabled)

    @property
    def notification_telegram_binding_enabled_effective(self) -> bool:
        """Доступна ли привязка Telegram-чата (binding). По умолчанию включено (sandbox)."""
        return bool(self.notifications_enabled and self.notification_telegram_binding_enabled)

    @property
    def notification_telegram_test_send_enabled_effective(self) -> bool:
        """Доступна ли тестовая Telegram-отправка (по умолчанию false — только dry-run)."""
        return bool(
            self.notification_telegram_templates_enabled_effective
            and self.notification_telegram_test_send_enabled
        )

    @property
    def notification_telegram_live_send_enabled_effective(self) -> bool:
        """Разрешена ли РЕАЛЬНАЯ Telegram-отправка. По умолчанию false — требует всех флагов.

        Нужны: внешняя доставка + telegram live + telegram live send + bot token настроен.
        """
        return bool(
            self.notification_telegram_enabled_effective
            and self.notification_telegram_live_send_enabled
            and self.notification_telegram_configured
        )

    @property
    def notification_telegram_binding_token_ttl_seconds(self) -> int:
        """TTL verification-токена в секундах (не меньше 1 часа)."""
        days = int(self.notification_telegram_binding_token_ttl_days or 30)
        return max(3600, days * 86400)

    @property
    def notification_telegram_max_message_chars_safe(self) -> int:
        """Максимум символов Telegram-сообщения (в границах 1..4096)."""
        return max(1, min(4096, int(self.notification_telegram_max_message_chars or 3900)))

    # --- Telegram webhook/polling: производные (effective) свойства (v0.5.5) ---

    @property
    def notification_telegram_webhook_enabled_effective(self) -> bool:
        """Доступен ли incoming webhook endpoint (по умолчанию включён — sandbox)."""
        return bool(self.notifications_enabled and self.notification_telegram_webhook_enabled)

    @property
    def notification_telegram_webhook_live_enabled_effective(self) -> bool:
        """Разрешён ли РЕАЛЬНЫЙ webhook наружу. По умолчанию false — требует всех флагов."""
        return bool(
            self.notification_external_delivery_enabled_effective
            and self.notification_telegram_webhook_live_enabled
            and self.notification_telegram_configured
        )

    @property
    def notification_telegram_webhook_secret_required_effective(self) -> bool:
        """Требуется ли secret-заголовок вебхука (по умолчанию false — local/sandbox)."""
        return bool(self.notification_telegram_webhook_secret_required)

    @property
    def notification_telegram_webhook_public_url_effective(self) -> str:
        """Публичный webhook URL: явный public_url + path, иначе только path."""
        base = str(self.notification_telegram_webhook_public_url or "").strip().rstrip("/")
        path = self.notification_telegram_webhook_path_effective
        return f"{base}{path}" if base else path

    @property
    def notification_telegram_webhook_path_effective(self) -> str:
        """Путь webhook-эндпоинта (нормализованный, с ведущим слэшем)."""
        path = str(self.notification_telegram_webhook_path or "").strip()
        if not path:
            return "/notification-telegram/webhook"
        return path if path.startswith("/") else f"/{path}"

    @property
    def notification_telegram_polling_enabled_effective(self) -> bool:
        """Доступен ли polling skeleton (dry-run; по умолчанию включён)."""
        return bool(self.notifications_enabled and self.notification_telegram_polling_enabled)

    @property
    def notification_telegram_polling_live_enabled_effective(self) -> bool:
        """Разрешён ли РЕАЛЬНЫЙ getUpdates. По умолчанию false — требует всех флагов."""
        return bool(
            self.notification_external_delivery_enabled_effective
            and self.notification_telegram_polling_live_enabled
            and self.notification_telegram_configured
        )

    @property
    def notification_telegram_polling_dry_run_effective(self) -> bool:
        """Dry-run polling (по умолчанию true — реального getUpdates нет)."""
        return bool(self.notification_telegram_polling_dry_run)

    @property
    def notification_telegram_polling_limit_safe(self) -> int:
        """Лимит getUpdates (в границах 1..100)."""
        return max(1, min(100, int(self.notification_telegram_polling_limit or 20)))

    @property
    def notification_telegram_webhook_management_enabled_effective(self) -> bool:
        """Доступно ли управление webhook (dry-run; по умолчанию включено)."""
        return bool(
            self.notifications_enabled and self.notification_telegram_webhook_management_enabled
        )

    @property
    def notification_telegram_webhook_management_live_enabled_effective(self) -> bool:
        """Разрешён ли РЕАЛЬНЫЙ setWebhook/deleteWebhook (по умолчанию false — нужны все флаги)."""
        return bool(
            self.notification_external_delivery_enabled_effective
            and self.notification_telegram_webhook_management_live_enabled
            and self.notification_telegram_configured
        )

    @property
    def notification_telegram_webhook_management_dry_run_effective(self) -> bool:
        """Dry-run управления webhook (по умолчанию true — реальных вызовов нет)."""
        return bool(self.notification_telegram_webhook_management_dry_run)

    @property
    def notification_telegram_incoming_max_text_preview_safe(self) -> int:
        """Максимум символов text_preview входящего апдейта (в границах 1..512)."""
        return max(1, min(512, int(self.notification_telegram_incoming_max_text_preview or 200)))

    # --- Autopilot-first workspace: производные (effective) свойства (v0.5.6) ---

    @property
    def autopilot_ui_enabled_effective(self) -> bool:
        """Доступен ли клиентский autopilot-workspace (по умолчанию включён)."""
        return bool(self.autopilot_ui_enabled)

    @property
    def autopilot_default_mode_safe(self) -> str:
        """Режим автопилота по умолчанию (full_auto/semi_auto; иначе full_auto)."""
        mode = str(self.autopilot_default_mode or "full_auto").strip().lower()
        return mode if mode in ("full_auto", "semi_auto") else "full_auto"

    @property
    def autopilot_full_auto_primary_effective(self) -> bool:
        """full_auto — основной режим продукта (по умолчанию true)."""
        return bool(self.autopilot_full_auto_primary)

    @property
    def autopilot_health_check_worker_enabled_effective(self) -> bool:
        """Включён ли фоновый health-worker автопилота (по умолчанию false)."""
        return bool(
            self.autopilot_health_check_enabled and self.autopilot_health_check_worker_enabled
        )

    @property
    def autopilot_health_check_dry_run_effective(self) -> bool:
        """Dry-run health-check (по умолчанию true — без побочных эффектов)."""
        return bool(self.autopilot_health_check_dry_run)

    @property
    def autopilot_auto_start_live_effective(self) -> bool:
        """Разрешён ли авто-старт live-публикации. По умолчанию false — live не включается из UI."""
        return bool(self.autopilot_auto_start_live)

    @property
    def autopilot_min_media_assets_safe(self) -> int:
        """Минимум медиа для автопилота (в границах 1..100)."""
        return max(1, min(100, int(self.autopilot_min_media_assets or 5)))

    @property
    def autopilot_recommended_media_assets_safe(self) -> int:
        """Рекомендуемый объём медиатеки (не меньше минимума)."""
        return max(
            self.autopilot_min_media_assets_safe,
            min(1000, int(self.autopilot_recommended_media_assets or 30)),
        )

    @property
    def autopilot_default_posts_per_day_safe(self) -> int:
        """Постов в день по умолчанию (в границах 1..10)."""
        return max(1, min(10, int(self.autopilot_default_posts_per_day or 1)))

    @property
    def autopilot_default_publish_time_safe(self) -> str:
        """Время публикации по умолчанию (HH:MM; иначе 10:00)."""
        raw = str(self.autopilot_default_publish_time or "10:00").strip()
        parts = raw.split(":")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            hh, mm = int(parts[0]), int(parts[1])
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                return f"{hh:02d}:{mm:02d}"
        return "10:00"

    @property
    def autopilot_default_timezone_safe(self) -> str:
        """Часовой пояс по умолчанию (непустой; иначе Europe/Moscow)."""
        return str(self.autopilot_default_timezone or "").strip() or "Europe/Moscow"

    # --- Yandex Disk auto-sync: производные (effective) свойства (v0.5.7) ---

    @property
    def yandex_auto_sync_enabled_effective(self) -> bool:
        """Доступна ли авто-синхронизация Яндекс Диска (UI/API; по умолчанию включено)."""
        return bool(self.yandex_auto_sync_enabled)

    @property
    def yandex_auto_sync_worker_enabled_effective(self) -> bool:
        """Включён ли фоновый sync-worker (по умолчанию false)."""
        return bool(self.yandex_auto_sync_enabled and self.yandex_auto_sync_worker_enabled)

    @property
    def yandex_auto_sync_dry_run_effective(self) -> bool:
        """Dry-run синхронизации (по умолчанию true — без записи медиа)."""
        return bool(self.yandex_auto_sync_dry_run)

    @property
    def yandex_auto_sync_network_enabled_effective(self) -> bool:
        """Разрешены ли реальные сетевые вызовы к Яндекс Диску. По умолчанию false (безопасно)."""
        return bool(self.yandex_auto_sync_network_enabled)

    @property
    def yandex_auto_sync_default_frequency_minutes_safe(self) -> int:
        """Частота синхронизации в минутах (в границах 5..1440)."""
        return max(5, min(1440, int(self.yandex_auto_sync_default_frequency_minutes or 60)))

    @property
    def yandex_auto_sync_max_projects_per_tick_safe(self) -> int:
        """Максимум проектов за один tick воркера (в границах 1..200)."""
        return max(1, min(200, int(self.yandex_auto_sync_max_projects_per_tick or 20)))

    @property
    def yandex_auto_sync_max_files_per_run_safe(self) -> int:
        """Максимум файлов за один прогон (в границах 1..5000)."""
        return max(1, min(5000, int(self.yandex_auto_sync_max_files_per_run or 500)))

    @property
    def yandex_auto_sync_min_media_assets_safe(self) -> int:
        """Минимум медиа для автопилота (в границах 1..100)."""
        return max(1, min(100, int(self.yandex_auto_sync_min_media_assets or 5)))

    @property
    def yandex_auto_sync_recommended_media_assets_safe(self) -> int:
        """Рекомендуемый объём медиатеки (не меньше минимума)."""
        return max(
            self.yandex_auto_sync_min_media_assets_safe,
            min(1000, int(self.yandex_auto_sync_recommended_media_assets or 30)),
        )

    # --- Autopilot Calendar Assistant: производные (effective) свойства (v0.5.8) ---

    @property
    def autopilot_calendar_assistant_enabled_effective(self) -> bool:
        """Доступен ли Calendar Assistant (по умолчанию включён)."""
        return bool(self.autopilot_calendar_assistant_enabled)

    @property
    def autopilot_calendar_assistant_dry_run_effective(self) -> bool:
        """Dry-run построения календаря (по умолчанию true — без записи)."""
        return bool(self.autopilot_calendar_assistant_dry_run)

    @property
    def autopilot_calendar_auto_apply_enabled_effective(self) -> bool:
        """Разрешено ли применение календаря к проекту (создание CrmPublishingPlan)."""
        return bool(
            self.autopilot_calendar_assistant_enabled and self.autopilot_calendar_auto_apply_enabled
        )

    @property
    def autopilot_calendar_default_preset_safe(self) -> str:
        """Пресет по умолчанию (из известных; иначе three_per_week)."""
        from app.models.autopilot_calendar_plan import AUTOPILOT_CALENDAR_PRESETS

        preset = str(self.autopilot_calendar_default_preset or "").strip().lower()
        return preset if preset in AUTOPILOT_CALENDAR_PRESETS else "three_per_week"

    @property
    def autopilot_calendar_default_goal_safe(self) -> str:
        """Цель по умолчанию (из известных; иначе mixed)."""
        from app.models.autopilot_calendar_plan import AUTOPILOT_CALENDAR_GOALS

        goal = str(self.autopilot_calendar_default_goal or "").strip().lower()
        return goal if goal in AUTOPILOT_CALENDAR_GOALS else "mixed"

    @property
    def autopilot_calendar_default_timezone_safe(self) -> str:
        """Часовой пояс по умолчанию (непустой; иначе Europe/Moscow)."""
        return str(self.autopilot_calendar_default_timezone or "").strip() or "Europe/Moscow"

    @property
    def autopilot_calendar_default_time_safe(self) -> str:
        """Время публикации по умолчанию (HH:MM; иначе 10:00)."""
        raw = str(self.autopilot_calendar_default_time or "10:00").strip()
        parts = raw.split(":")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            hh, mm = int(parts[0]), int(parts[1])
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                return f"{hh:02d}:{mm:02d}"
        return "10:00"

    @property
    def autopilot_calendar_max_posts_per_day_safe(self) -> int:
        """Максимум постов в день (в границах 1..10)."""
        return max(1, min(10, int(self.autopilot_calendar_max_posts_per_day or 3)))

    @property
    def autopilot_calendar_max_platforms_safe(self) -> int:
        """Максимум площадок в календаре (в границах 1..10)."""
        return max(1, min(10, int(self.autopilot_calendar_max_platforms or 5)))

    # --- Live autopost readiness (v0.5.9): производные (effective) свойства ---

    @property
    def live_readiness_enabled_effective(self) -> bool:
        """Доступен ли live-readiness audit (по умолчанию включён)."""
        return bool(self.live_readiness_enabled)

    @property
    def live_readiness_dry_run_effective(self) -> bool:
        """Dry-run проверок готовности (по умолчанию true — без записи профилей)."""
        return bool(self.live_readiness_dry_run)

    @property
    def live_readiness_worker_enabled_effective(self) -> bool:
        """Включён ли фоновый worker readiness (по умолчанию выключен)."""
        return bool(self.live_readiness_enabled and self.live_readiness_worker_enabled)

    @property
    def live_readiness_require_confirmation_effective(self) -> bool:
        """Требуется ли явное подтверждение перед включением live (по умолчанию да)."""
        return bool(self.live_readiness_require_confirmation)

    @property
    def live_readiness_min_score_to_enable_safe(self) -> int:
        """Порог готовности для включения live (в границах 0..100; иначе 85)."""
        return max(0, min(100, int(self.live_readiness_min_score_to_enable or 85)))

    @property
    def live_readiness_probe_external_api_effective(self) -> bool:
        """Разрешены ли реальные внешние probe-вызовы (по умолчанию НЕТ)."""
        return bool(self.live_readiness_probe_external_api)

    @property
    def live_autopilot_enable_ui_effective(self) -> bool:
        """Показывать ли UI готовности к автопубликации (по умолчанию да)."""
        return bool(self.live_readiness_enabled and self.live_autopilot_enable_ui)

    @property
    def live_autopilot_enable_api_effective(self) -> bool:
        """Доступно ли API готовности к автопубликации (по умолчанию да)."""
        return bool(self.live_readiness_enabled and self.live_autopilot_enable_api)

    @property
    def live_autopilot_confirmation_text_safe(self) -> str:
        """Текст подтверждения включения live для проекта (непустой)."""
        return str(self.live_autopilot_confirmation_text or "").strip() or "ENABLE_LIVE_AUTOPILOT"

    @property
    def live_platform_confirmation_text_safe(self) -> str:
        """Текст подтверждения включения live для площадки (непустой)."""
        return str(self.live_platform_confirmation_text or "").strip() or "ENABLE_PLATFORM_LIVE"

    # --- Telegram-first live rollout (v0.6.0): производные (effective) свойства ---

    @property
    def telegram_live_rollout_enabled_effective(self) -> bool:
        """Доступен ли Telegram live rollout (UI/API/CLI)."""
        return bool(self.telegram_live_rollout_enabled)

    @property
    def telegram_live_rollout_dry_run_effective(self) -> bool:
        """Dry-run rollout по умолчанию (без реальной отправки)."""
        return bool(self.telegram_live_rollout_dry_run)

    @property
    def telegram_live_rollout_run_once_enabled_effective(self) -> bool:
        """Доступен ли run-once flow (по умолчанию да; сама отправка — за allow_real_send)."""
        return bool(
            self.telegram_live_rollout_enabled and self.telegram_live_rollout_run_once_enabled
        )

    @property
    def telegram_live_rollout_allow_real_send_effective(self) -> bool:
        """Разрешена ли РЕАЛЬНАЯ отправка (по умолчанию НЕТ; глобальный флаг всё равно нужен)."""
        return bool(
            self.telegram_live_rollout_enabled and self.telegram_live_rollout_allow_real_send
        )

    @property
    def telegram_live_rollout_require_confirmation_effective(self) -> bool:
        """Требуется ли подтверждение перед live-попыткой (по умолчанию да)."""
        return bool(self.telegram_live_rollout_require_confirmation)

    @property
    def telegram_live_rollout_confirmation_text_safe(self) -> str:
        """Текст подтверждения включения Telegram live (непустой)."""
        raw = str(self.telegram_live_rollout_confirmation_text or "").strip()
        return raw or "ENABLE_TELEGRAM_LIVE"

    @property
    def telegram_live_rollout_max_attempts_per_post_safe(self) -> int:
        """Максимум live-попыток на один пост (в границах 1..10)."""
        return max(1, min(10, int(self.telegram_live_rollout_max_attempts_per_post or 1)))

    # --- Telegram live production runbook (v0.6.3): производные свойства ---

    @property
    def telegram_runbook_enabled_effective(self) -> bool:
        """Доступен ли Telegram runbook (UI/API/CLI)."""
        return bool(self.telegram_runbook_enabled)

    @property
    def telegram_runbook_dry_run_effective(self) -> bool:
        """Dry-run runbook по умолчанию (проверка не пишет в БД)."""
        return bool(self.telegram_runbook_dry_run)

    # --- Live autopilot monitoring & kill switch (v0.6.1): производные свойства ---

    @property
    def live_autopilot_monitoring_enabled_effective(self) -> bool:
        """Доступен ли мониторинг live-автопилота (UI/API/CLI)."""
        return bool(self.live_autopilot_monitoring_enabled)

    @property
    def live_autopilot_monitoring_dry_run_effective(self) -> bool:
        """Dry-run мониторинга по умолчанию (без записи снимков)."""
        return bool(self.live_autopilot_monitoring_dry_run)

    @property
    def live_autopilot_monitoring_worker_enabled_effective(self) -> bool:
        """Включён ли фоновый worker мониторинга (по умолчанию выключен)."""
        return bool(
            self.live_autopilot_monitoring_enabled and self.live_autopilot_monitoring_worker_enabled
        )

    @property
    def live_autopilot_incidents_enabled_effective(self) -> bool:
        """Включено ли создание инцидентов (по умолчанию да)."""
        return bool(
            self.live_autopilot_monitoring_enabled and self.live_autopilot_incidents_enabled
        )

    @property
    def live_autopilot_auto_pause_enabled_effective(self) -> bool:
        """Разрешена ли АВТО-пауза автопилота (по умолчанию НЕТ)."""
        return bool(self.live_autopilot_auto_pause_enabled)

    @property
    def live_autopilot_kill_switch_enabled_effective(self) -> bool:
        """Доступен ли kill switch (пауза/возобновление, по умолчанию да)."""
        return bool(self.live_autopilot_kill_switch_enabled)

    @property
    def live_autopilot_monitoring_window_seconds(self) -> int:
        """Окно наблюдения в секундах (из часов; в границах 1..168 ч)."""
        hours = max(1, min(168, int(self.live_autopilot_monitoring_window_hours or 24)))
        return hours * 3600

    @property
    def live_autopilot_incident_dedup_seconds(self) -> int:
        """Окно дедупликации инцидентов в секундах (из часов; в границах 0..168 ч)."""
        hours = max(0, min(168, int(self.live_autopilot_incident_dedup_hours or 24)))
        return hours * 3600

    @property
    def live_autopilot_pause_confirmation_text_safe(self) -> str:
        """Текст подтверждения паузы автопилота (непустой)."""
        return str(self.live_autopilot_pause_confirmation_text or "").strip() or "PAUSE_AUTOPILOT"

    @property
    def live_autopilot_resume_confirmation_text_safe(self) -> str:
        """Текст подтверждения возобновления автопилота (непустой)."""
        return str(self.live_autopilot_resume_confirmation_text or "").strip() or "RESUME_AUTOPILOT"

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
