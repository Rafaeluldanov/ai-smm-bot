"""SQLAlchemy-модели. Импорт здесь регистрирует их в общих метаданных Base."""

from app.db.base import Base
from app.models.account import Account
from app.models.account_membership import AccountMembership
from app.models.app_mention import AppMention
from app.models.app_notification import AppNotification
from app.models.audit_log import AuditLogEntry
from app.models.auth_session import AuthSession
from app.models.autonomous_run import AutonomousRun
from app.models.autonomous_run_step import AutonomousRunStep
from app.models.autopilot_calendar_plan import AutopilotCalendarPlan
from app.models.billing import (
    BillingAccount,
    BillingLedgerEntry,
    TariffPlan,
    UsageEvent,
)
from app.models.client_learning_profile import ClientLearningProfile
from app.models.content_experiment import ContentExperiment
from app.models.content_experiment_variant import ContentExperimentVariant
from app.models.crm_bot_smm import (
    CrmBotProjectConfig,
    CrmContentSource,
    CrmKeyword,
    CrmOnboardingDraft,
    CrmPromotionCategory,
    CrmPublishingPlan,
    CrmSmmResource,
)
from app.models.email_template_override import EmailTemplateOverride
from app.models.experiment_suggestion import ExperimentSuggestion
from app.models.external_image_candidate import ExternalImageCandidate
from app.models.live_autopilot_incident import LiveAutopilotIncident
from app.models.live_autopilot_monitor_snapshot import LiveAutopilotMonitorSnapshot
from app.models.live_publish_attempt import LivePublishAttempt
from app.models.media_asset import MediaAsset
from app.models.media_asset_variant import MediaAssetVariant
from app.models.media_curation_comment import MediaCurationComment
from app.models.media_curation_task import MediaCurationTask
from app.models.media_duplicate_cluster import MediaDuplicateCluster
from app.models.media_fingerprint import MediaFingerprint
from app.models.media_proxy_access_log import MediaProxyAccessLog
from app.models.media_quality_snapshot import MediaQualitySnapshot
from app.models.metric_import_run import MetricImportRun
from app.models.notification_delivery_log import NotificationDeliveryLog
from app.models.notification_digest import NotificationDigest
from app.models.notification_opt_out import NotificationOptOut
from app.models.notification_preference import NotificationPreference
from app.models.notification_rate_limit_bucket import NotificationRateLimitBucket
from app.models.notification_suppression import NotificationSuppression
from app.models.notification_telegram_binding import NotificationTelegramBinding
from app.models.notification_telegram_update_log import NotificationTelegramUpdateLog
from app.models.onboarding_session import OnboardingSession
from app.models.onboarding_step_result import OnboardingStepResult
from app.models.payment import (
    BillingProfile,
    PaymentInvoice,
    PaymentTransaction,
    PaymentWebhookLog,
)
from app.models.platform_live_readiness import PlatformLiveReadiness
from app.models.post import Post
from app.models.post_analytics_snapshot import PostAnalyticsSnapshot
from app.models.post_feedback_event import PostFeedbackEvent
from app.models.post_publication import PostPublication
from app.models.post_review_action import PostReviewAction
from app.models.project import Project
from app.models.project_autopilot_profile import ProjectAutopilotProfile
from app.models.project_live_readiness_profile import ProjectLiveReadinessProfile
from app.models.project_yandex_sync_profile import ProjectYandexSyncProfile
from app.models.public_media_link import PublicMediaLink
from app.models.schedule_media_decision import ScheduleMediaDecision
from app.models.schedule_run import ScheduleRun
from app.models.schedule_topic_decision import ScheduleTopicDecision
from app.models.scheduler_worker_lease import SchedulerWorkerLease
from app.models.telegram_live_run_attempt import TelegramLiveRunAttempt
from app.models.telegram_live_runbook import TelegramLiveRunbook
from app.models.topic import Topic
from app.models.user import User
from app.models.webhook_subscription import WebhookSubscription
from app.models.yandex_auto_sync_run import YandexAutoSyncRun

__all__ = [
    "Account",
    "AccountMembership",
    "AppMention",
    "AppNotification",
    "AuditLogEntry",
    "AuthSession",
    "AutonomousRun",
    "AutopilotCalendarPlan",
    "AutonomousRunStep",
    "Base",
    "BillingAccount",
    "BillingLedgerEntry",
    "ClientLearningProfile",
    "ContentExperiment",
    "ContentExperimentVariant",
    "CrmBotProjectConfig",
    "CrmContentSource",
    "CrmKeyword",
    "CrmOnboardingDraft",
    "CrmPromotionCategory",
    "CrmPublishingPlan",
    "CrmSmmResource",
    "EmailTemplateOverride",
    "ExperimentSuggestion",
    "ExternalImageCandidate",
    "LiveAutopilotIncident",
    "LiveAutopilotMonitorSnapshot",
    "LivePublishAttempt",
    "ScheduleMediaDecision",
    "ScheduleTopicDecision",
    "BillingProfile",
    "MediaAsset",
    "MediaAssetVariant",
    "MediaProxyAccessLog",
    "MediaCurationComment",
    "MediaCurationTask",
    "MediaDuplicateCluster",
    "MediaFingerprint",
    "MediaQualitySnapshot",
    "MetricImportRun",
    "NotificationDeliveryLog",
    "NotificationDigest",
    "NotificationOptOut",
    "NotificationPreference",
    "NotificationRateLimitBucket",
    "NotificationSuppression",
    "NotificationTelegramBinding",
    "NotificationTelegramUpdateLog",
    "OnboardingSession",
    "OnboardingStepResult",
    "PaymentInvoice",
    "PaymentTransaction",
    "PaymentWebhookLog",
    "PlatformLiveReadiness",
    "Post",
    "PostAnalyticsSnapshot",
    "PostFeedbackEvent",
    "PostPublication",
    "PostReviewAction",
    "Project",
    "ProjectAutopilotProfile",
    "ProjectLiveReadinessProfile",
    "ProjectYandexSyncProfile",
    "PublicMediaLink",
    "ScheduleRun",
    "SchedulerWorkerLease",
    "TariffPlan",
    "TelegramLiveRunAttempt",
    "TelegramLiveRunbook",
    "Topic",
    "UsageEvent",
    "User",
    "WebhookSubscription",
    "YandexAutoSyncRun",
]
