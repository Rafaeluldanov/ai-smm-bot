"""Сервис аудит-лога SaaS: запись действий и чтение по аккаунту.

Аудит НИКОГДА не роняет основное действие: при ``AUDIT_LOG_ENABLED=false`` запись
пропускается, а исключения при записи проглатываются (логируются в приложении, но не
пробрасываются). Метаданные санитизируются через ``core.redaction`` — секреты в аудит
не попадают.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.core.redaction import sanitize_metadata
from app.models.audit_log import AuditLogEntry
from app.repositories import audit_log_repository

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)

# Действия аудита (стабильные строковые коды).
ACTION_USER_REGISTERED = "user.registered"
ACTION_USER_LOGIN = "user.login"
ACTION_USER_LOGOUT = "user.logout"
ACTION_USER_REFRESH = "user.refresh"
ACTION_USER_SESSION_REVOKED = "user.session.revoked"
ACTION_USER_LOGOUT_ALL = "user.logout_all"
ACTION_PROJECT_CREATED = "project.created"
ACTION_PROJECT_UPDATED = "project.updated"
ACTION_PLATFORM_CONNECTED = "platform.connected"
ACTION_PLATFORM_SECRET_UPDATED = "platform.secret.updated"
# Self-service подключения платформ (v0.3.6).
ACTION_CONNECTION_CREATED = "platform.connection.created"
ACTION_CONNECTION_UPDATED = "platform.connection.updated"
ACTION_CONNECTION_SECRET_UPDATED = "platform.connection.secret.updated"
ACTION_CONNECTION_CHECKED = "platform.connection.checked"
ACTION_CONNECTION_CHECK_FAILED = "platform.connection.check.failed"
ACTION_CONNECTION_DELETED = "platform.connection.deleted"
# Media proxy: публичные ссылки на медиа (v0.3.7).
ACTION_MEDIA_PROXY_LINK_CREATED = "media_proxy.link.created"
ACTION_MEDIA_PROXY_LINK_REVOKED = "media_proxy.link.revoked"
ACTION_MEDIA_PROXY_LINK_EXPIRED = "media_proxy.link.expired"
# Schedule automation: движок автоматизации расписаний (v0.3.8).
ACTION_SCHEDULE_RUN_PREVIEW = "schedule.run.preview"
ACTION_SCHEDULE_RUN_STARTED = "schedule.run.started"
ACTION_SCHEDULE_RUN_DRAFT_CREATED = "schedule.run.draft_created"
ACTION_SCHEDULE_RUN_SKIPPED = "schedule.run.skipped"
ACTION_SCHEDULE_RUN_FAILED = "schedule.run.failed"
ACTION_SCHEDULE_RUN_INSUFFICIENT_BALANCE = "schedule.run.insufficient_balance"
ACTION_SCHEDULE_RUN_MISSING_CREDENTIALS = "schedule.run.missing_credentials"
# Background scheduler worker (v0.3.9).
ACTION_WORKER_TICK_STARTED = "scheduler.worker.tick.started"
ACTION_WORKER_TICK_FINISHED = "scheduler.worker.tick.finished"
ACTION_WORKER_TICK_FAILED = "scheduler.worker.tick.failed"
ACTION_WORKER_TARGET_PROCESSED = "scheduler.worker.target.processed"
ACTION_WORKER_LEASE_ACQUIRED = "scheduler.worker.lease.acquired"
ACTION_WORKER_LEASE_SKIPPED = "scheduler.worker.lease.skipped"
ACTION_SCHEDULE_CREATED = "schedule.created"
ACTION_SCHEDULE_UPDATED = "schedule.updated"
ACTION_SCHEDULE_DELETED = "schedule.deleted"
ACTION_ANALYTICS_RUN = "analytics.run"
ACTION_INVOICE_CREATED = "billing.invoice.created"
ACTION_INVOICE_PAID = "billing.invoice.paid"
ACTION_INVOICE_FAILED = "billing.invoice.failed"
ACTION_INVOICE_CANCELED = "billing.invoice.canceled"
ACTION_INVOICE_EXPIRED = "billing.invoice.expired"
ACTION_BALANCE_DEBITED = "billing.balance.debited"
ACTION_BALANCE_CREDITED = "billing.balance.credited"
ACTION_OAUTH_CONNECTED = "oauth.connected"
ACTION_OAUTH_FAILED = "oauth.failed"
# Review / approval workflow + обучение + автоматизация (v0.4.0).
ACTION_REVIEW_POST_OPENED = "review.post.opened"
ACTION_REVIEW_POST_EDITED = "review.post.edited"
ACTION_REVIEW_POST_APPROVED = "review.post.approved"
ACTION_REVIEW_POST_REJECTED = "review.post.rejected"
ACTION_REVIEW_POST_CHANGES_REQUESTED = "review.post.changes_requested"
ACTION_REVIEW_POST_PUBLISH_CLICKED = "review.post.publish_clicked"
ACTION_REVIEW_POST_PUBLISH_BLOCKED = "review.post.publish_blocked"
ACTION_REVIEW_POST_PUBLISHED = "review.post.published"
ACTION_LEARNING_FEEDBACK_RECORDED = "learning.feedback.recorded"
ACTION_LEARNING_PROFILE_UPDATED = "learning.profile.updated"
ACTION_LEARNING_PROFILE_REBUILT = "learning.profile.rebuilt"
ACTION_AUTOMATION_MODE_CHANGED = "automation.mode.changed"
ACTION_AUTOMATION_FULL_AUTO_ENABLED = "automation.full_auto.enabled"
ACTION_AUTOMATION_FULL_AUTO_DISABLED = "automation.full_auto.disabled"
ACTION_AUTOMATION_AUTO_PUBLISH_BLOCKED = "automation.auto_publish.blocked"
ACTION_AUTOMATION_AUTO_PUBLISH_SUCCEEDED = "automation.auto_publish.succeeded"
# Импорт метрик и обратная связь обучения (v0.4.1).
ACTION_METRICS_IMPORT_PREVIEW = "metrics.import.preview"
ACTION_METRICS_IMPORT_STARTED = "metrics.import.started"
ACTION_METRICS_IMPORT_COMPLETED = "metrics.import.completed"
ACTION_METRICS_IMPORT_FAILED = "metrics.import.failed"
ACTION_METRICS_IMPORT_BLOCKED = "metrics.import.blocked"
ACTION_METRICS_MANUAL_SAVED = "metrics.manual.saved"
ACTION_METRICS_LEARNING_REBUILD_PREVIEW = "metrics.learning.rebuild.preview"
ACTION_METRICS_LEARNING_REBUILT = "metrics.learning.rebuilt"
ACTION_METRICS_EXTERNAL_API_DISABLED = "metrics.external_api.disabled"
# A/B-тестирование и оптимизация тем (v0.4.2).
ACTION_EXPERIMENT_CREATED = "experiment.created"
ACTION_EXPERIMENT_VARIANT_CREATED = "experiment.variant.created"
ACTION_EXPERIMENT_SCORED = "experiment.scored"
ACTION_EXPERIMENT_FEEDBACK_RECORDED = "experiment.feedback.recorded"
ACTION_EXPERIMENT_WINNER_SELECTED = "experiment.winner.selected"
ACTION_EXPERIMENT_COMPLETED = "experiment.completed"
ACTION_EXPERIMENT_CANCELED = "experiment.canceled"
ACTION_OPTIMIZATION_RECOMMENDATIONS_GENERATED = "optimization.recommendations.generated"
ACTION_OPTIMIZATION_TOPIC_SELECTED = "optimization.topic.selected"
ACTION_AB_TEST_PREVIEWED = "ab_test.previewed"
ACTION_AB_TEST_BLOCKED = "ab_test.blocked"
# Предложения экспериментов worker-ом (v0.4.3).
ACTION_EXP_SUGGESTION_PREVIEWED = "experiment_suggestion.previewed"
ACTION_EXP_SUGGESTION_GENERATED = "experiment_suggestion.generated"
ACTION_EXP_SUGGESTION_CREATED = "experiment_suggestion.created"
ACTION_EXP_SUGGESTION_ACCEPTED = "experiment_suggestion.accepted"
ACTION_EXP_SUGGESTION_REJECTED = "experiment_suggestion.rejected"
ACTION_EXP_SUGGESTION_DISMISSED = "experiment_suggestion.dismissed"
ACTION_EXP_SUGGESTION_EXPERIMENT_CREATED = "experiment_suggestion.experiment_created"
ACTION_EXP_SUGGESTION_FAILED = "experiment_suggestion.failed"
ACTION_WORKER_EXP_SUGGESTIONS_PREVIEWED = "scheduler.worker.experiment_suggestions.previewed"
ACTION_WORKER_EXP_SUGGESTIONS_CREATED = "scheduler.worker.experiment_suggestions.created"
ACTION_WORKER_EXP_SUGGESTIONS_SKIPPED = "scheduler.worker.experiment_suggestions.skipped"
ACTION_WORKER_EXPERIMENT_CREATED = "scheduler.worker.experiment_created"
ACTION_WORKER_EXP_SUGGESTIONS_FAILED = "scheduler.worker.experiment_suggestions.failed"
# Автовыбор темы worker-ом (v0.4.4).
ACTION_TOPIC_DECISION_PREVIEWED = "topic_decision.previewed"
ACTION_TOPIC_DECISION_CREATED = "topic_decision.created"
ACTION_TOPIC_DECISION_APPLIED_TO_DRAFT = "topic_decision.applied_to_draft"
ACTION_TOPIC_DECISION_FAILED = "topic_decision.failed"
ACTION_TOPIC_DECISION_LOW_CONFIDENCE = "topic_decision.low_confidence"
ACTION_TOPIC_DECISION_FALLBACK_USED = "topic_decision.fallback_used"
ACTION_WORKER_TOPIC_DECISION_PREVIEWED = "scheduler.worker.topic_decision.previewed"
ACTION_WORKER_TOPIC_DECISION_CREATED = "scheduler.worker.topic_decision.created"
ACTION_WORKER_TOPIC_DECISION_SKIPPED = "scheduler.worker.topic_decision.skipped"
ACTION_WORKER_TOPIC_DECISION_FAILED = "scheduler.worker.topic_decision.failed"
# Автовыбор медиа worker-ом (v0.4.5).
ACTION_MEDIA_DECISION_PREVIEWED = "media_decision.previewed"
ACTION_MEDIA_DECISION_CREATED = "media_decision.created"
ACTION_MEDIA_DECISION_APPLIED_TO_DRAFT = "media_decision.applied_to_draft"
ACTION_MEDIA_DECISION_FAILED = "media_decision.failed"
ACTION_MEDIA_DECISION_LOW_CONFIDENCE = "media_decision.low_confidence"
ACTION_MEDIA_DECISION_NO_MEDIA = "media_decision.no_media"
ACTION_MEDIA_DECISION_FALLBACK_USED = "media_decision.fallback_used"
ACTION_WORKER_MEDIA_DECISION_PREVIEWED = "scheduler.worker.media_decision.previewed"
ACTION_WORKER_MEDIA_DECISION_CREATED = "scheduler.worker.media_decision.created"
ACTION_WORKER_MEDIA_DECISION_SKIPPED = "scheduler.worker.media_decision.skipped"
ACTION_WORKER_MEDIA_DECISION_FAILED = "scheduler.worker.media_decision.failed"
# Оценка качества медиа (v0.4.6).
ACTION_MEDIA_QUALITY_PREVIEWED = "media_quality.previewed"
ACTION_MEDIA_QUALITY_SCORED = "media_quality.scored"
ACTION_MEDIA_QUALITY_FAILED = "media_quality.failed"
ACTION_MEDIA_QUALITY_WEAK_DETECTED = "media_quality.weak_detected"
ACTION_MEDIA_QUALITY_DUPLICATE_DETECTED = "media_quality.duplicate_detected"
ACTION_WORKER_MEDIA_QUALITY_PREVIEWED = "scheduler.worker.media_quality.previewed"
ACTION_WORKER_MEDIA_QUALITY_SCORED = "scheduler.worker.media_quality.scored"
ACTION_WORKER_MEDIA_QUALITY_FAILED = "scheduler.worker.media_quality.failed"
# Fingerprint и дедупликация медиа (v0.4.7).
ACTION_MEDIA_FINGERPRINT_PREVIEWED = "media_fingerprint.previewed"
ACTION_MEDIA_FINGERPRINT_CALCULATED = "media_fingerprint.calculated"
ACTION_MEDIA_FINGERPRINT_FAILED = "media_fingerprint.failed"
ACTION_MEDIA_DUPLICATE_PREVIEWED = "media_duplicate.previewed"
ACTION_MEDIA_DUPLICATE_CLUSTER_CREATED = "media_duplicate.cluster_created"
ACTION_MEDIA_DUPLICATE_REVIEWED = "media_duplicate.reviewed"
ACTION_MEDIA_DUPLICATE_IGNORED = "media_duplicate.ignored"
ACTION_MEDIA_DUPLICATE_RESOLVED = "media_duplicate.resolved"
ACTION_WORKER_MEDIA_FINGERPRINT_PREVIEWED = "scheduler.worker.media_fingerprint.previewed"
ACTION_WORKER_MEDIA_FINGERPRINT_CREATED = "scheduler.worker.media_fingerprint.created"
ACTION_WORKER_MEDIA_FINGERPRINT_FAILED = "scheduler.worker.media_fingerprint.failed"
ACTION_WORKER_DUPLICATE_CLUSTER_PREVIEWED = "scheduler.worker.duplicate_cluster.previewed"
ACTION_WORKER_DUPLICATE_CLUSTER_CREATED = "scheduler.worker.duplicate_cluster.created"
# Курирование медиатеки (v0.4.8).
ACTION_MEDIA_CURATION_PREVIEWED = "media_curation.previewed"
ACTION_MEDIA_CURATION_TASK_CREATED = "media_curation.task_created"
ACTION_MEDIA_CURATION_TASK_APPLIED = "media_curation.task_applied"
ACTION_MEDIA_CURATION_TASK_REJECTED = "media_curation.task_rejected"
ACTION_MEDIA_CURATION_TASK_IGNORED = "media_curation.task_ignored"
ACTION_MEDIA_CURATION_MEDIA_HIDDEN = "media_curation.media_hidden"
ACTION_MEDIA_CURATION_MEDIA_RESTORED = "media_curation.media_restored"
ACTION_MEDIA_CURATION_TAGS_APPLIED = "media_curation.tags_applied"
ACTION_WORKER_MEDIA_CURATION_PREVIEWED = "scheduler.worker.media_curation.previewed"
ACTION_WORKER_MEDIA_CURATION_CREATED = "scheduler.worker.media_curation.created"
ACTION_WORKER_MEDIA_CURATION_FAILED = "scheduler.worker.media_curation.failed"
# Collaborative media curation review (v0.4.9).
ACTION_MEDIA_CURATION_REVIEW_COMMENT_ADDED = "media_curation_review.comment_added"
ACTION_MEDIA_CURATION_REVIEW_ASSIGNED = "media_curation_review.assigned"
ACTION_MEDIA_CURATION_REVIEW_UNASSIGNED = "media_curation_review.unassigned"
ACTION_MEDIA_CURATION_REVIEW_STARTED = "media_curation_review.started"
ACTION_MEDIA_CURATION_REVIEW_CHANGES_REQUESTED = "media_curation_review.changes_requested"
ACTION_MEDIA_CURATION_REVIEW_APPROVED = "media_curation_review.approved"
ACTION_MEDIA_CURATION_REVIEW_REJECTED = "media_curation_review.rejected"
ACTION_MEDIA_CURATION_REVIEW_APPLIED = "media_curation_review.applied"
ACTION_MEDIA_CURATION_REVIEW_IGNORED = "media_curation_review.ignored"
ACTION_MEDIA_CURATION_REVIEW_RESTORED = "media_curation_review.restored"
ACTION_MEDIA_CURATION_REVIEW_OVERDUE = "media_curation_review.overdue"


class AuditLogService:
    """Запись/чтение аудита действий (безопасно, без секретов)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings

    def _enabled(self) -> bool:
        settings = self._settings
        if settings is None:
            from app.config import get_settings

            settings = get_settings()
        return bool(settings.audit_log_enabled)

    @staticmethod
    def sanitize_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
        """Очистить метаданные от секретов (через core.redaction)."""
        if not metadata:
            return {}
        cleaned = sanitize_metadata(metadata)
        return cleaned if isinstance(cleaned, dict) else {}

    def record(
        self,
        db: Session,
        action: str,
        *,
        account_id: int | None = None,
        user_id: int | None = None,
        project_id: int | None = None,
        entity_type: str = "",
        entity_id: str | int | None = None,
        metadata: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLogEntry | None:
        """Записать событие аудита. Никогда не роняет основное действие."""
        if not self._enabled():
            return None
        try:
            return audit_log_repository.create_entry(
                db,
                account_id=account_id,
                user_id=user_id,
                project_id=project_id,
                action=action,
                entity_type=entity_type,
                entity_id=None if entity_id is None else str(entity_id),
                ip_address=ip_address,
                user_agent=(user_agent or "")[:512] or None,
                entry_metadata=self.sanitize_metadata(metadata),
            )
        except Exception:  # noqa: BLE001 — аудит не должен ронять основное действие
            logger.warning("audit-log record failed for action=%s", action, exc_info=False)
            with contextlib.suppress(Exception):
                db.rollback()
            return None

    def list_for_account(
        self, db: Session, account_id: int, limit: int = 100, offset: int = 0
    ) -> list[AuditLogEntry]:
        """Записи аудита аккаунта (свежие первыми)."""
        return audit_log_repository.list_for_account(db, account_id, limit, offset)


def get_audit_log_service() -> AuditLogService:
    """DI-фабрика сервиса аудита."""
    return AuditLogService()
