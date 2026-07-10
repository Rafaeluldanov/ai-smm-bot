"""Зависимости FastAPI (dependency injection)."""

from collections.abc import Iterator
from typing import TYPE_CHECKING, Annotated

if TYPE_CHECKING:
    from app.services.payments.payment_service import PaymentService
    from app.services.post_analytics_service import PostAnalyticsService

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
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


def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Извлечь текущего пользователя из dev-токена (Authorization). 401 — если нет.

    Это dev-заглушка авторизации (не продакшн-JWT): токен подписан, но реальная
    сессионная система появится позже.
    """
    user_id = parse_dev_token(authorization or "")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация (dev-токен в заголовке Authorization)",
        )
    user = user_repository.get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Пользователь не найден или неактивен"
        )
    return user
