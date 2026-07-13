"""Зависимости FastAPI (dependency injection)."""

from collections.abc import Iterator
from typing import TYPE_CHECKING, Annotated

if TYPE_CHECKING:
    from app.services.ab_testing_service import ABTestingService
    from app.services.auth_session_service import AuthSessionService
    from app.services.auth_token_service import AuthTokenService
    from app.services.automation_settings_service import AutomationSettingsService
    from app.services.autopilot_calendar_assistant_service import (
        AutopilotCalendarAssistantService,
    )
    from app.services.autopilot_service import AutopilotService
    from app.services.client_learning_service import ClientLearningService
    from app.services.content_scoring_service import ContentScoringService
    from app.services.email_template_service import EmailTemplateService
    from app.services.experiment_suggestion_service import ExperimentSuggestionService
    from app.services.live_readiness_service import LiveReadinessService
    from app.services.media_curation_review_service import MediaCurationReviewService
    from app.services.media_curation_service import MediaCurationService
    from app.services.media_fingerprint_service import MediaFingerprintService
    from app.services.media_quality_service import MediaQualityService
    from app.services.media_similarity_service import MediaSimilarityService
    from app.services.metrics_import_service import MetricsImportService
    from app.services.notification_delivery_service import NotificationDeliveryService
    from app.services.notification_digest_service import NotificationDigestService
    from app.services.notification_rate_limit_service import NotificationRateLimitService
    from app.services.notification_service import NotificationService
    from app.services.notification_suppression_service import NotificationSuppressionService
    from app.services.notification_telegram_binding_service import (
        NotificationTelegramBindingService,
    )
    from app.services.notification_unsubscribe_service import NotificationUnsubscribeService
    from app.services.payments.payment_service import PaymentService
    from app.services.post_analytics_service import PostAnalyticsService
    from app.services.review_workflow_service import ReviewWorkflowService
    from app.services.schedule_media_decision_service import ScheduleMediaDecisionService
    from app.services.schedule_topic_decision_service import ScheduleTopicDecisionService
    from app.services.telegram_bot_management_service import TelegramBotManagementService
    from app.services.telegram_incoming_service import TelegramIncomingService
    from app.services.telegram_notification_template_service import (
        TelegramNotificationTemplateService,
    )
    from app.services.topic_optimization_service import TopicOptimizationService
    from app.services.webhook_subscription_service import WebhookSubscriptionService
    from app.services.yandex_auto_sync_service import YandexAutoSyncService

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.security import parse_dev_token
from app.db.session import get_session
from app.integrations.instagram.client import InstagramPublishingClient
from app.integrations.rutube.client import RuTubePublishingClient
from app.integrations.telegram.client import TelegramPublishingClient
from app.integrations.vk.client import VKPublishingClient
from app.integrations.yandex_disk.client import YandexDiskClient, YandexDiskPublicClient
from app.integrations.youtube.client import YouTubePublishingClient
from app.models.user import User
from app.repositories import user_repository
from app.services.analytics_provider import FakeAnalyticsProvider
from app.services.analytics_service import AnalyticsService
from app.services.auth_service import AuthService
from app.services.autonomous_pipeline_service import AutonomousPipelineService
from app.services.autonomous_safety_service import AutonomousSafetyService
from app.services.billing_service import BillingService
from app.services.crm_bot_smm_application_service import CrmBotSmmApplicationService
from app.services.crm_bot_smm_form_service import CrmBotSmmFormService
from app.services.external_image_provider import FakeExternalImageProvider
from app.services.external_image_provider_registry import ExternalImageProviderRegistry
from app.services.external_image_search_service import ExternalImageSearchService
from app.services.image_enhancement_processor import ImageEnhancementProcessor
from app.services.market_signal_provider import StaticMarketSignalProvider
from app.services.media_analysis_service import MediaAnalysisService
from app.services.media_download_service import MediaDownloadService
from app.services.media_enhancement_service import MediaEnhancementService
from app.services.media_grouping_service import MediaGroupingService
from app.services.media_status_service import MediaStatusService
from app.services.media_tagging_service import MediaTaggingService
from app.services.post_generation_service import PostGenerationService
from app.services.post_media_selection_service import PostMediaSelectionService
from app.services.post_publication_service import PostPublicationService
from app.services.post_review_service import PostReviewService
from app.services.public_yandex_disk_media_sync_service import (
    PublicYandexDiskMediaSyncService,
)
from app.services.publication_platform_registry import PublicationPlatformRegistry
from app.services.saas_bot_run_service import SaasBotRunService
from app.services.saas_onboarding_service import SaasOnboardingService
from app.services.topic_selection_service import TopicSelectionService
from app.services.vk_oauth_service import VkOAuthService
from app.services.yandex_disk_media_sync_service import YandexDiskMediaSyncService


def get_db() -> Iterator[Session]:
    """Выдать сессию БД на время запроса и гарантированно закрыть её.

    Делегирует в :func:`app.db.session.get_session`, чтобы не дублировать
    логику жизненного цикла сессии.
    """
    yield from get_session()


def get_yandex_disk_client() -> YandexDiskClient:
    """Построить клиент Яндекс Диска из настроек.

    Токен может быть пустым — ошибка возникнет только при реальном запросе
    (см. ``YandexDiskAuthError``), поэтому эндпоинты без обращения к Диску
    работают и без токена.
    """
    settings = get_settings()
    return YandexDiskClient(
        token=settings.yandex_disk_token,
        base_url=settings.yandex_disk_base_url,
    )


def get_media_sync_service(
    client: Annotated[YandexDiskClient, Depends(get_yandex_disk_client)],
) -> YandexDiskMediaSyncService:
    """Построить сервис синхронизации медиа (для тестов подменяется клиент)."""
    return YandexDiskMediaSyncService(client=client, tagging_service=MediaTaggingService())


def get_public_yandex_disk_client() -> YandexDiskPublicClient:
    """Построить публичный клиент Яндекс Диска (без токена)."""
    settings = get_settings()
    return YandexDiskPublicClient(base_url=settings.yandex_disk_base_url)


def get_public_media_sync_service(
    client: Annotated[YandexDiskPublicClient, Depends(get_public_yandex_disk_client)],
) -> PublicYandexDiskMediaSyncService:
    """Построить сервис публичной синхронизации медиа (в тестах подменяется)."""
    settings = get_settings()
    return PublicYandexDiskMediaSyncService(
        client=client,
        tagging_service=MediaTaggingService(),
        public_key=settings.yandex_disk_public_smm_url or None,
        root_folder=settings.yandex_disk_public_root_folder,
    )


def get_image_enhancement_processor() -> ImageEnhancementProcessor:
    """Построить процессор локального улучшения изображений (Pillow)."""
    settings = get_settings()
    return ImageEnhancementProcessor(
        output_format=settings.media_enhancement_output_format,
        jpeg_quality=settings.media_enhancement_jpeg_quality,
        max_image_mb=settings.media_enhancement_max_image_mb,
    )


def get_media_download_service() -> MediaDownloadService:
    """Построить загрузчик медиа (публичная папка Яндекс Диска; в тестах подменяется)."""
    settings = get_settings()
    return MediaDownloadService(
        public_client=YandexDiskPublicClient(base_url=settings.yandex_disk_base_url),
        public_key=settings.yandex_disk_public_smm_url or None,
    )


def get_media_enhancement_service(
    processor: Annotated[ImageEnhancementProcessor, Depends(get_image_enhancement_processor)],
    downloader: Annotated[MediaDownloadService, Depends(get_media_download_service)],
) -> MediaEnhancementService:
    """Построить сервис улучшения медиа (создаёт копии, не трогает оригиналы)."""
    settings = get_settings()
    return MediaEnhancementService(
        processor=processor,
        downloader=downloader,
        storage_dir=settings.media_enhancement_storage_dir,
        default_profile=settings.media_enhancement_default_profile,
    )


def get_media_status_service() -> MediaStatusService:
    """Построить сервис статусов медиа."""
    return MediaStatusService()


def get_media_analysis_service() -> MediaAnalysisService:
    """Построить сервис анализа/ретегирования медиа."""
    return MediaAnalysisService(
        tagging_service=MediaTaggingService(),
        status_service=MediaStatusService(),
    )


def get_media_grouping_service() -> MediaGroupingService:
    """Построить сервис группировки медиа и сборки поста по группе."""
    return MediaGroupingService()


def get_topic_selection_service() -> TopicSelectionService:
    """Построить сервис выбора тем и контент-плана."""
    return TopicSelectionService(
        market_provider=StaticMarketSignalProvider(),
        media_analysis_service=get_media_analysis_service(),
    )


def get_post_generation_service() -> PostGenerationService:
    """Построить сервис генерации постов (подбор медиа + выбор тем)."""
    return PostGenerationService(
        media_selection_service=PostMediaSelectionService(),
        topic_selection_service=get_topic_selection_service(),
    )


def get_post_review_service() -> PostReviewService:
    """Построить сервис согласования постов."""
    return PostReviewService()


def get_content_scoring_service() -> "ContentScoringService":
    """Построить сервис эвристической оценки контента (без БД/сети)."""
    from app.services.content_scoring_service import ContentScoringService

    return ContentScoringService()


def get_client_learning_service() -> "ClientLearningService":
    """Построить движок обучения бота на клиенте (per-project профиль)."""
    from app.services.client_learning_service import ClientLearningService

    return ClientLearningService(scoring_service=get_content_scoring_service())


def get_automation_settings_service() -> "AutomationSettingsService":
    """Построить сервис настроек режима автоматизации (semi_auto|full_auto)."""
    from app.services.automation_settings_service import AutomationSettingsService

    return AutomationSettingsService()


def get_topic_optimization_service() -> "TopicOptimizationService":
    """Построить сервис оптимизации тем и рекомендаций (без сети)."""
    from app.services.topic_optimization_service import TopicOptimizationService

    return TopicOptimizationService(
        learning_service=get_client_learning_service(), settings=get_settings()
    )


def get_ab_testing_service() -> "ABTestingService":
    """Построить сервис A/B-тестирования (варианты в ревью, без live-публикации)."""
    from app.services.ab_testing_service import ABTestingService

    return ABTestingService(
        learning_service=get_client_learning_service(),
        billing_service=get_billing_service(),
        settings=get_settings(),
    )


def get_experiment_suggestion_service() -> "ExperimentSuggestionService":
    """Построить сервис предложений экспериментов (worker/клиент, без live-публикации)."""
    from app.services.experiment_suggestion_service import ExperimentSuggestionService

    return ExperimentSuggestionService(
        billing_service=get_billing_service(), settings=get_settings()
    )


def get_topic_decision_service() -> "ScheduleTopicDecisionService":
    """Построить сервис автовыбора темы (worker/клиент, без live-публикации)."""
    from app.services.schedule_topic_decision_service import ScheduleTopicDecisionService

    return ScheduleTopicDecisionService(settings=get_settings())


def get_media_decision_service() -> "ScheduleMediaDecisionService":
    """Построить сервис автовыбора медиа (worker/клиент, без live-публикации).

    Пост создаётся только как draft/needs_review; публичные ссылки автоматически не
    создаются; внешних API-вызовов нет.
    """
    from app.services.schedule_media_decision_service import ScheduleMediaDecisionService

    return ScheduleMediaDecisionService(settings=get_settings())


def get_media_quality_service() -> "MediaQualityService":
    """Построить сервис оценки качества медиа (правило-ориентированный, без внешнего AI/live)."""
    from app.services.media_quality_service import MediaQualityService

    return MediaQualityService(settings=get_settings())


def get_media_fingerprint_service() -> "MediaFingerprintService":
    """Построить сервис fingerprint медиа (локальные хэши; без внешнего AI/сети/live)."""
    from app.services.media_fingerprint_service import MediaFingerprintService

    return MediaFingerprintService(settings=get_settings())


def get_media_similarity_service() -> "MediaSimilarityService":
    """Построить сервис похожести/дедупликации медиа (в пределах проекта; без внешнего AI)."""
    from app.services.media_similarity_service import MediaSimilarityService

    return MediaSimilarityService(settings=get_settings())


def get_media_curation_service() -> "MediaCurationService":
    """Построить сервис курирования медиатеки (без внешнего AI; без авто-apply/hide/delete)."""
    from app.services.media_curation_service import MediaCurationService

    return MediaCurationService(settings=get_settings())


def get_media_curation_review_service() -> "MediaCurationReviewService":
    """Построить сервис collaborative review медиатеки (approve-before-apply; без AI/delete)."""
    from app.services.media_curation_review_service import MediaCurationReviewService

    return MediaCurationReviewService(
        curation_service=get_media_curation_service(),
        settings=get_settings(),
        notification_service=get_notification_service(),
    )


def get_notification_service() -> "NotificationService":
    """Построить сервис внутренних уведомлений (in-app; без внешней доставки)."""
    from app.services.notification_service import NotificationService

    return NotificationService(settings=get_settings())


def get_notification_delivery_service() -> "NotificationDeliveryService":
    """Построить сервис доставки уведомлений (sandbox; без реальной внешней доставки)."""
    from app.services.notification_delivery_service import NotificationDeliveryService

    return NotificationDeliveryService(settings=get_settings())


def get_notification_digest_service() -> "NotificationDigestService":
    """Построить сервис дайджестов уведомлений (без реальной отправки; выключен по умолчанию)."""
    from app.services.notification_digest_service import NotificationDigestService

    return NotificationDigestService(settings=get_settings())


def get_notification_unsubscribe_service() -> "NotificationUnsubscribeService":
    """Построить сервис отписки (opt-out) уведомлений."""
    from app.services.notification_unsubscribe_service import NotificationUnsubscribeService

    return NotificationUnsubscribeService(settings=get_settings())


def get_notification_rate_limit_service() -> "NotificationRateLimitService":
    """Построить сервис rate-limit доставки уведомлений."""
    from app.services.notification_rate_limit_service import NotificationRateLimitService

    return NotificationRateLimitService(settings=get_settings())


def get_notification_suppression_service() -> "NotificationSuppressionService":
    """Построить сервис подавления доставки уведомлений."""
    from app.services.notification_suppression_service import NotificationSuppressionService

    return NotificationSuppressionService(settings=get_settings())


def get_webhook_subscription_service() -> "WebhookSubscriptionService":
    """Построить сервис webhook-подписок (encrypted/masked; live-вызов выключен)."""
    from app.services.webhook_subscription_service import WebhookSubscriptionService

    return WebhookSubscriptionService(settings=get_settings())


def get_email_template_service() -> "EmailTemplateService":
    """Построить сервис email-шаблонов (preview/render; реальной отправки нет)."""
    from app.services.email_template_service import EmailTemplateService

    return EmailTemplateService(settings=get_settings())


def get_telegram_notification_template_service() -> "TelegramNotificationTemplateService":
    """Построить сервис Telegram-шаблонов (preview/render; реальной отправки нет)."""
    from app.services.telegram_notification_template_service import (
        TelegramNotificationTemplateService,
    )

    return TelegramNotificationTemplateService(settings=get_settings())


def get_notification_telegram_binding_service() -> "NotificationTelegramBindingService":
    """Построить сервис привязок Telegram-чата (chat_id encrypted/masked; sandbox по умолчанию)."""
    from app.services.notification_telegram_binding_service import (
        NotificationTelegramBindingService,
    )

    return NotificationTelegramBindingService(settings=get_settings())


def get_telegram_incoming_service() -> "TelegramIncomingService":
    """Построить сервис входящих Telegram-апдейтов (webhook/polling sandbox; без сети)."""
    from app.services.telegram_incoming_service import TelegramIncomingService

    return TelegramIncomingService(settings=get_settings())


def get_telegram_bot_management_service() -> "TelegramBotManagementService":
    """Построить сервис управления Telegram-ботом (setWebhook/getUpdates dry-run; без сети)."""
    from app.services.telegram_bot_management_service import TelegramBotManagementService

    return TelegramBotManagementService(settings=get_settings())


def get_autopilot_service() -> "AutopilotService":
    """Построить сервис автопилота (оркестратор поверх подсистем; без live-публикаций)."""
    from app.services.autopilot_service import AutopilotService

    return AutopilotService(settings=get_settings())


def get_autopilot_calendar_assistant_service() -> "AutopilotCalendarAssistantService":
    """Построить сервис Calendar Assistant (строит календарь; не публикует, live не трогает)."""
    from app.services.autopilot_calendar_assistant_service import (
        AutopilotCalendarAssistantService,
    )

    return AutopilotCalendarAssistantService(settings=get_settings())


def get_live_readiness_service() -> "LiveReadinessService":
    """Построить сервис live-readiness (аудит готовности; live-флаги НЕ включает и не обходит)."""
    from app.services.live_readiness_service import LiveReadinessService

    return LiveReadinessService(settings=get_settings())


def get_yandex_auto_sync_service() -> "YandexAutoSyncService":
    """Построить сервис авто-синхронизации Яндекс Диска (dry-run/без сети по умолчанию)."""
    from app.services.yandex_auto_sync_service import YandexAutoSyncService

    return YandexAutoSyncService(settings=get_settings())


def get_metrics_import_service() -> "MetricsImportService":
    """Построить сервис импорта метрик и обратной связи обучения (без сети по умолчанию)."""
    from app.services.metrics_import_service import MetricsImportService

    return MetricsImportService(
        learning_service=get_client_learning_service(),
        billing_service=get_billing_service(),
        settings=get_settings(),
    )


def get_review_workflow_service() -> "ReviewWorkflowService":
    """Построить оркестратор review/approval workflow (очередь, решения, publish-now)."""
    from app.services.review_workflow_service import ReviewWorkflowService

    return ReviewWorkflowService(
        review_service=get_post_review_service(),
        learning_service=get_client_learning_service(),
        publication_service=get_post_publication_service(get_publication_platform_registry()),
        billing_service=get_billing_service(),
    )


def get_publication_platform_registry() -> PublicationPlatformRegistry:
    """Построить реестр клиентов публикации (безопасные клиенты из настроек).

    Реальная отправка включается ТОЛЬКО при включённых флагах
    ``TELEGRAM_LIVE_PUBLISHING_ENABLED`` / ``VK_LIVE_PUBLISHING_ENABLED`` (по
    умолчанию выключены — публикация невозможна). В тестах реестр подменяется на
    фейковый.
    """
    settings = get_settings()
    return PublicationPlatformRegistry(
        {
            "telegram": TelegramPublishingClient(
                token=settings.telegram_bot_token or None,
                default_target_id=settings.telegram_default_channel_id,
                live_enabled=settings.telegram_live_publishing_enabled,
                # Загрузчик публичного медиа для фотоальбома (сеть — только на live-пути).
                media_downloader=get_media_download_service(),
                # Конвертер HEIC/HEIF → JPEG в памяти (оригинал не меняется).
                image_processor=get_image_enhancement_processor(),
                max_media_group_photos=settings.telegram_media_group_max_photos,
            ),
            "vk": VKPublishingClient(
                token=settings.vk_access_token or None,
                default_target_id=settings.vk_default_group_id,
                live_enabled=settings.vk_live_publishing_enabled,
                # Загрузчик публичного медиа для фото-вложения (сеть — только на live-пути).
                media_downloader=get_media_download_service(),
                # Конвертер HEIC/HEIF → JPEG в памяти (оригинал не меняется).
                image_processor=get_image_enhancement_processor(),
                max_group_photos=settings.vk_media_group_max_photos,
                # Стратегия загрузки фото: auto → wall, при error 27 → album.
                photo_upload_strategy=settings.vk_photo_upload_strategy,
                photo_album_id=settings.vk_photo_album_id,
                photo_album_title=settings.vk_photo_album_title,
            ),
            # Adapter-скелеты: preview/dry-run работает, live пока не реализован.
            "instagram": InstagramPublishingClient(
                token=settings.instagram_access_token or None,
                default_target_id=settings.instagram_business_account_id,
                live_enabled=settings.instagram_live_publishing_enabled,
            ),
            "youtube": YouTubePublishingClient(
                token=settings.youtube_access_token or None,
                default_target_id=settings.youtube_channel_id,
                live_enabled=settings.youtube_live_publishing_enabled,
            ),
            "rutube": RuTubePublishingClient(
                token=settings.rutube_access_token or None,
                default_target_id=settings.rutube_channel_id,
                live_enabled=settings.rutube_live_publishing_enabled,
            ),
        }
    )


def get_post_publication_service(
    registry: Annotated[PublicationPlatformRegistry, Depends(get_publication_platform_registry)],
) -> PostPublicationService:
    """Построить сервис планирования и публикации постов."""
    settings = get_settings()
    return PostPublicationService(
        registry=registry,
        default_targets={
            "telegram": settings.telegram_default_channel_id,
            "vk": settings.vk_default_group_id,
            "instagram": settings.instagram_business_account_id,
            "youtube": settings.youtube_channel_id,
            "rutube": settings.rutube_channel_id,
        },
    )


def get_analytics_provider() -> FakeAnalyticsProvider:
    """Построить провайдер метрик (fake на Этапе 8 — без сети)."""
    return FakeAnalyticsProvider()


def get_analytics_service(
    provider: Annotated[FakeAnalyticsProvider, Depends(get_analytics_provider)],
) -> AnalyticsService:
    """Построить сервис аналитики публикаций."""
    return AnalyticsService(provider=provider)


def get_external_image_provider_registry() -> ExternalImageProviderRegistry:
    """Построить реестр провайдеров внешних изображений (fake на Этапе 9)."""
    return ExternalImageProviderRegistry({"fake": FakeExternalImageProvider()})


def get_external_image_search_service(
    registry: Annotated[
        ExternalImageProviderRegistry, Depends(get_external_image_provider_registry)
    ],
) -> ExternalImageSearchService:
    """Построить сервис поиска внешних изображений."""
    return ExternalImageSearchService(registry=registry, tagging_service=MediaTaggingService())


def get_autonomous_safety_service() -> AutonomousSafetyService:
    """Построить сервис safety-guardrails автономного режима."""
    return AutonomousSafetyService()


def get_autonomous_pipeline_service() -> AutonomousPipelineService:
    """Построить сервис автономного pipeline (связывает все этапы)."""
    return AutonomousPipelineService(
        topic_selection_service=get_topic_selection_service(),
        post_generation_service=get_post_generation_service(),
        post_review_service=get_post_review_service(),
        post_publication_service=get_post_publication_service(get_publication_platform_registry()),
        external_image_search_service=get_external_image_search_service(
            get_external_image_provider_registry()
        ),
        analytics_service=get_analytics_service(get_analytics_provider()),
        safety_service=get_autonomous_safety_service(),
    )


def get_crm_bot_smm_form_service() -> CrmBotSmmFormService:
    """Построить сервис формы «БОТ СММ» (схема, валидация, apply, превью)."""
    return CrmBotSmmFormService()


def get_crm_bot_smm_application_service() -> CrmBotSmmApplicationService:
    """Построить сервис интеграции конфигурации CRM с SEO-модулями и pipeline."""
    return CrmBotSmmApplicationService(pipeline_service=get_autonomous_pipeline_service())


# --- SaaS: auth / billing / onboarding / прогон ---


def get_auth_service() -> AuthService:
    """Построить сервис аутентификации и провижининга аккаунтов."""
    return AuthService()


def get_billing_service() -> BillingService:
    """Построить сервис биллинга (депозит в units, списания, usage)."""
    return BillingService()


def get_post_analytics_service() -> "PostAnalyticsService":
    """Построить сервис аналитики постов (офлайн: анализ, оценка, платный отчёт)."""
    from app.services.post_analytics_service import PostAnalyticsService

    return PostAnalyticsService(billing_service=get_billing_service())


def get_payment_service() -> "PaymentService":
    """Построить сервис платежей (mock/sandbox; реальные платежи выключены)."""
    from app.services.payments.payment_service import PaymentService

    return PaymentService(billing_service=get_billing_service())


def get_saas_onboarding_service() -> SaasOnboardingService:
    """Построить сервис SaaS-онбординга (переиспользует CRM-конфигуратор)."""
    return SaasOnboardingService(
        crm_form_service=get_crm_bot_smm_form_service(),
        billing_service=get_billing_service(),
    )


def get_saas_bot_run_service() -> SaasBotRunService:
    """Построить сервис безопасного прогона проекта с биллингом."""
    return SaasBotRunService(
        billing_service=get_billing_service(),
        crm_application_service=get_crm_bot_smm_application_service(),
    )


def get_vk_oauth_service() -> VkOAuthService:
    """Построить сервис VK OAuth connect flow (реальные HTTP — только к VK)."""
    return VkOAuthService(settings=get_settings())


def _resolve_token_user(
    db: Session, settings: Settings, authorization: str | None, cookie_token: str | None
) -> User | None:
    """Разрешить пользователя из access-токена (Bearer/cookie) или dev-токена.

    Приоритет: 1) access-токен (HMAC) из Authorization Bearer или cookie; 2) dev-токен
    — только если ``auth_allow_dev_token_effective`` (вне production). Некорректный/
    просроченный токен → None. Существование пользователя по чужому токену не
    раскрывается (всегда None).
    """
    from app.services.auth_token_service import AuthTokenService

    raw: str | None = None
    if authorization:
        raw = (
            authorization[7:].strip()
            if authorization.lower().startswith("bearer ")
            else authorization.strip()
        )
    candidate = raw or cookie_token
    if candidate:
        payload = AuthTokenService(settings).verify_access_token(candidate)
        if payload is not None:
            user = user_repository.get_user_by_id(db, payload.user_id)
            if user is not None and user.is_active:
                return user
    # dev-токен — только вне production и при auth_allow_dev_token.
    if settings.auth_allow_dev_token_effective and authorization:
        dev_id = parse_dev_token(authorization)
        if dev_id is not None:
            user = user_repository.get_user_by_id(db, dev_id)
            if user is not None and user.is_active:
                return user
    return None


def get_current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Текущий пользователь из access-токена (Bearer/cookie) или dev-токена. 401 — если нет.

    В production dev-токен запрещён; отсутствие/просрочка/подделка токена → 401. Ответ
    не раскрывает, существует ли пользователь.
    """
    cookie_token = request.cookies.get(settings.auth_session_cookie_name)
    user = _resolve_token_user(db, settings, authorization, cookie_token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_auth_token_service() -> "AuthTokenService":
    """Построить сервис access/refresh-токенов."""
    from app.services.auth_token_service import AuthTokenService

    return AuthTokenService()


def get_auth_session_service() -> "AuthSessionService":
    """Построить сервис серверных сессий (login/refresh/logout)."""
    from app.services.auth_session_service import AuthSessionService

    return AuthSessionService()


def get_optional_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> User | None:
    """Вернуть пользователя по access/dev-токену или None (без ошибки при отсутствии).

    Нужна tenant-guard'ам: если пользователь аутентифицирован — доступ строго
    проверяется; анонимные запросы допускаются только вне production (dev/local),
    где включён back-compat для существующих тестов и локальной разработки.
    """
    cookie_token = request.cookies.get(settings.auth_session_cookie_name)
    return _resolve_token_user(db, settings, authorization, cookie_token)
