"""Точка входа FastAPI-приложения."""

import logging

from fastapi import FastAPI

from app.api.ai_campaigns import router as ai_campaigns_router
from app.api.ai_learning import router as ai_learning_router
from app.api.analytics import router as analytics_router
from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.automation import router as automation_router
from app.api.autonomous_runs import router as autonomous_runs_router
from app.api.autopilot import router as autopilot_router
from app.api.autopilot_calendar import router as autopilot_calendar_router
from app.api.billing import router as billing_router
from app.api.content_strategy import router as content_strategy_router
from app.api.crm_bot_smm import router as crm_bot_smm_router
from app.api.email_templates import router as email_templates_router
from app.api.experiment_suggestions import router as experiment_suggestions_router
from app.api.experiments import router as experiments_router
from app.api.external_images import router as external_images_router
from app.api.health import router as health_router
from app.api.integrations_vk import router as integrations_vk_router
from app.api.live_autopilot_monitoring import router as live_autopilot_monitoring_router
from app.api.live_readiness import router as live_readiness_router
from app.api.media_assets import router as media_assets_router
from app.api.media_curation import router as media_curation_router
from app.api.media_curation_review import router as media_curation_review_router
from app.api.media_decisions import router as media_decisions_router
from app.api.media_enhancements import router as media_enhancements_router
from app.api.media_fingerprints import router as media_fingerprints_router
from app.api.media_proxy import public_router as media_public_router
from app.api.media_proxy import router as media_proxy_router
from app.api.media_proxy import tokens_router as media_proxy_tokens_router
from app.api.media_quality import router as media_quality_router
from app.api.metrics_import import router as metrics_import_router
from app.api.notification_delivery import router as notification_delivery_router
from app.api.notification_safety import router as notification_safety_router
from app.api.notification_telegram import router as notification_telegram_router
from app.api.notifications import router as notifications_router
from app.api.onboarding import router as onboarding_router
from app.api.platform_connections import router as platform_connections_router
from app.api.post_publications import router as post_publications_router
from app.api.post_reviews import router as post_reviews_router
from app.api.posts import router as posts_router
from app.api.projects import router as projects_router
from app.api.review_workflow import router as review_workflow_router
from app.api.saas_onboarding import router as saas_router
from app.api.sales_intelligence import router as sales_intelligence_router
from app.api.schedule_automation import router as schedule_automation_router
from app.api.scheduler_worker import router as scheduler_worker_router
from app.api.security_middleware import (
    CSRFMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from app.api.seo import router as seo_router
from app.api.telegram_live_rollout import router as telegram_live_rollout_router
from app.api.telegram_live_runbook import router as telegram_live_runbook_router
from app.api.topic_decisions import router as topic_decisions_router
from app.api.topics import router as topics_router
from app.api.ui import router as ui_router
from app.api.yandex_auto_sync import router as yandex_auto_sync_router
from app.config import get_settings, production_security_errors
from app.core.logging import configure_logging, get_logger
from app.middleware.request_logging import AccessLogMiddleware, RequestIDMiddleware


def create_app() -> FastAPI:
    """Сконфигурировать и вернуть экземпляр FastAPI."""
    settings = get_settings()
    log_level = getattr(logging, settings.log_level.strip().upper(), logging.INFO)
    configure_logging(log_level if isinstance(log_level, int) else logging.INFO)
    logger = get_logger(__name__)

    # Fail-fast: в production приложение не стартует с небезопасной auth-конфигурацией.
    fatal = production_security_errors(settings)
    if fatal:
        raise RuntimeError("Небезопасная конфигурация для production: " + "; ".join(fatal))

    app = FastAPI(
        title="AI-SMM-бот",
        version="0.1.0",
        summary="Автоматическое ведение соцсетей проектов компании",
    )
    # Middleware (порядок: последний добавленный — внешний). Наблюдаемость снаружи
    # (request-id → access-log), затем security headers → rate limit → CSRF.
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(RequestIDMiddleware)

    app.include_router(health_router)
    app.include_router(projects_router)
    app.include_router(media_assets_router)
    app.include_router(media_enhancements_router)
    app.include_router(topics_router)
    app.include_router(posts_router)
    app.include_router(post_reviews_router)
    app.include_router(review_workflow_router)
    app.include_router(automation_router)
    app.include_router(metrics_import_router)
    app.include_router(experiments_router)
    app.include_router(experiment_suggestions_router)
    app.include_router(topic_decisions_router)
    app.include_router(media_decisions_router)
    app.include_router(media_quality_router)
    app.include_router(media_fingerprints_router)
    app.include_router(media_curation_router)
    app.include_router(media_curation_review_router)
    app.include_router(notifications_router)
    app.include_router(onboarding_router)
    app.include_router(ai_learning_router)
    app.include_router(content_strategy_router)
    app.include_router(ai_campaigns_router)
    app.include_router(sales_intelligence_router)
    app.include_router(notification_delivery_router)
    app.include_router(notification_safety_router)
    app.include_router(notification_telegram_router)
    app.include_router(email_templates_router)
    app.include_router(post_publications_router)
    app.include_router(analytics_router)
    app.include_router(platform_connections_router)
    app.include_router(media_proxy_router)
    app.include_router(media_proxy_tokens_router)
    app.include_router(media_public_router)
    app.include_router(schedule_automation_router)
    app.include_router(scheduler_worker_router)
    app.include_router(external_images_router)
    app.include_router(autonomous_runs_router)
    app.include_router(autopilot_router)
    app.include_router(autopilot_calendar_router)
    app.include_router(live_readiness_router)
    app.include_router(live_autopilot_monitoring_router)
    app.include_router(telegram_live_rollout_router)
    app.include_router(telegram_live_runbook_router)
    app.include_router(yandex_auto_sync_router)
    app.include_router(seo_router)
    app.include_router(crm_bot_smm_router)
    app.include_router(auth_router)
    app.include_router(billing_router)
    app.include_router(saas_router)
    app.include_router(audit_router)
    app.include_router(integrations_vk_router)
    app.include_router(ui_router)

    logger.info("Приложение инициализировано (env=%s)", settings.app_env)
    return app


app = create_app()
