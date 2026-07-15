"""SQLAlchemy-модели. Импорт здесь регистрирует их в общих метаданных Base."""

from app.db.base import Base
from app.models.account import Account
from app.models.account_membership import AccountMembership
from app.models.ai_business_task import AIBusinessTask
from app.models.ai_campaign import AICampaign
from app.models.ai_campaign_recommendation import AICampaignRecommendation
from app.models.ai_campaign_stage import AICampaignStage
from app.models.ai_decision import AIDecision
from app.models.ai_executive_plan import AIExecutivePlan
from app.models.ai_lead_event import AILeadEvent
from app.models.ai_learning_event import AILearningEvent
from app.models.ai_learning_profile import AILearningProfile
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
from app.models.business_action import BusinessAction
from app.models.business_decision_memory import BusinessDecisionMemory
from app.models.business_growth_profile import BusinessGrowthProfile
from app.models.business_growth_recommendation import BusinessGrowthRecommendation
from app.models.business_objective import BusinessObjective
from app.models.business_workflow import BusinessWorkflow
from app.models.client_learning_profile import ClientLearningProfile
from app.models.content_experiment import ContentExperiment
from app.models.content_experiment_variant import ContentExperimentVariant
from app.models.content_revenue_attribution import ContentRevenueAttribution
from app.models.content_strategy_profile import ContentStrategyProfile
from app.models.content_strategy_recommendation import ContentStrategyRecommendation
from app.models.crm_bot_smm import (
    CrmBotProjectConfig,
    CrmContentSource,
    CrmKeyword,
    CrmOnboardingDraft,
    CrmPromotionCategory,
    CrmPublishingPlan,
    CrmSmmResource,
)
from app.models.decision_scenario import DecisionScenario
from app.models.decision_signal import DecisionSignal
from app.models.email_template_override import EmailTemplateOverride
from app.models.executive_briefing import ExecutiveBriefing
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
from app.models.operations_recommendation import OperationsRecommendation
from app.models.operations_risk import OperationsRisk
from app.models.operations_snapshot import OperationsSnapshot
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
from app.models.sales_intelligence_profile import SalesIntelligenceProfile
from app.models.schedule_media_decision import ScheduleMediaDecision
from app.models.schedule_run import ScheduleRun
from app.models.schedule_topic_decision import ScheduleTopicDecision
from app.models.scheduler_worker_lease import SchedulerWorkerLease
from app.models.telegram_live_run_attempt import TelegramLiveRunAttempt
from app.models.telegram_live_runbook import TelegramLiveRunbook
from app.models.topic import Topic
from app.models.user import User
from app.models.webhook_subscription import WebhookSubscription
from app.models.workflow_blocker import WorkflowBlocker
from app.models.workflow_step import WorkflowStep
from app.models.yandex_auto_sync_run import YandexAutoSyncRun

__all__ = [
    "AIBusinessTask",
    "AICampaign",
    "AICampaignRecommendation",
    "AICampaignStage",
    "AIDecision",
    "AIExecutivePlan",
    "AILeadEvent",
    "AILearningEvent",
    "AILearningProfile",
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
    "BusinessAction",
    "BusinessDecisionMemory",
    "BusinessGrowthProfile",
    "BusinessGrowthRecommendation",
    "BusinessObjective",
    "BusinessWorkflow",
    "ClientLearningProfile",
    "ContentExperiment",
    "ContentRevenueAttribution",
    "ContentStrategyProfile",
    "ContentStrategyRecommendation",
    "ContentExperimentVariant",
    "SalesIntelligenceProfile",
    "CrmBotProjectConfig",
    "CrmContentSource",
    "CrmKeyword",
    "CrmOnboardingDraft",
    "CrmPromotionCategory",
    "CrmPublishingPlan",
    "CrmSmmResource",
    "DecisionScenario",
    "DecisionSignal",
    "EmailTemplateOverride",
    "ExecutiveBriefing",
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
    "OperationsRecommendation",
    "OperationsRisk",
    "OperationsSnapshot",
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
    "WorkflowBlocker",
    "WorkflowStep",
    "YandexAutoSyncRun",
]
