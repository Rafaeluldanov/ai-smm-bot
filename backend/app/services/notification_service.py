"""Сервис внутренних (in-app) уведомлений, упоминаний и нагрузки ревьюеров — v0.5.0.

Централизует создание уведомлений (назначения, упоминания, статусы, просрочки), inbox
пользователя, дашборд проекта и workload ревьюеров с SLA. Доставка ТОЛЬКО внутренняя;
внешняя (email/digest/webhook/push) выключена и в MVP не производится.

БЕЗОПАСНОСТЬ:
- title/message/metadata санитизируются (без секретов, токенов и внутренних путей);
- строго recipient/project/account-scoped; без межклиентских уведомлений;
- создание уведомления НИКОГДА не должно ронять основное действие (hooks безопасны).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, TypeVar

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.redaction import redact_sensitive_text, sanitize_metadata
from app.models.app_notification import (
    NOTIFICATION_PRIORITIES,
    NOTIFICATION_TYPES,
)
from app.repositories import (
    account_repository,
    media_curation_repository,
    notification_repository,
    project_repository,
)
from app.repositories import media_curation_review_repository as review_repo
from app.services import audit_log_service as audit_actions
from app.services import mention_parser_service as mentions

if TYPE_CHECKING:
    from app.config import Settings
    from app.models.app_mention import AppMention
    from app.models.app_notification import AppNotification
    from app.models.notification_preference import NotificationPreference
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

_R = TypeVar("_R")

_INTERNAL_PATH_RE = re.compile(
    r"(?i)(?:disk:/\S+|/(?:Users|home|var|etc|tmp|mnt|srv|opt|root)/\S+|[A-Za-z]:\\\S+)"
)
_ACTIVE_REVIEW_STATUSES = ("proposed", "assigned", "in_review", "changes_requested", "approved")
# Отображение нового review_status → тип уведомления (для notify_status_change).
_STATUS_NOTIFICATION_TYPE = {
    "changes_requested": "review_changes_requested",
    "approved": "review_approved",
    "rejected": "review_rejected",
    "applied": "review_applied",
}


def sanitize_text(text: str, limit: int = 2000) -> str:
    """Очистить текст уведомления от секретов и внутренних путей."""
    cleaned = redact_sensitive_text(text or "")
    cleaned = _INTERNAL_PATH_RE.sub("[путь скрыт]", cleaned)
    return cleaned.strip()[:limit]


class NotificationError(Exception):
    """Ошибка уведомлений (нет доступа/сущности) — API → 400/403/404."""


class NotificationService:
    """Внутренние уведомления, упоминания, inbox, дашборд, workload ревьюеров."""

    def __init__(
        self, audit_service: AuditLogService | None = None, settings: Settings | None = None
    ) -> None:
        self._audit = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # 1. Создание уведомления                                             #
    # ------------------------------------------------------------------ #

    def create_notification(
        self,
        db: Session,
        recipient_user_id: int | None,
        notification_type: str,
        title: str,
        message: str,
        account_id: int | None = None,
        project_id: int | None = None,
        actor_user_id: int | None = None,
        entity_type: str | None = None,
        entity_id: str | int | None = None,
        priority: str = "normal",
        action_url: str | None = None,
        due_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Создать in-app уведомление (с дедупликацией). Возвращает view или None (no-op)."""
        if not self._enabled() or not self._in_app_enabled():
            return None
        if recipient_user_id is None:
            return None  # некому — тихо пропускаем
        if notification_type not in NOTIFICATION_TYPES:
            notification_type = "system_notice"
        if priority not in NOTIFICATION_PRIORITIES:
            priority = "normal"
        entity_id_str = None if entity_id is None else str(entity_id)

        # Дедупликация: не спамим одинаковыми непрочитанными в окне.
        window = self._dedup_seconds()
        if window > 0:
            since = datetime.now(UTC) - timedelta(seconds=window)
            existing = notification_repository.find_duplicate_recent(
                db, recipient_user_id, notification_type, entity_type, entity_id_str, since
            )
            if existing is not None:
                return self._view(existing)

        notification = notification_repository.create_notification(
            db,
            account_id=account_id,
            project_id=project_id,
            recipient_user_id=recipient_user_id,
            actor_user_id=actor_user_id,
            notification_type=notification_type,
            channel="in_app",
            status="unread",
            priority=priority,
            title=sanitize_text(title, 255),
            message=sanitize_text(message),
            entity_type=entity_type,
            entity_id=entity_id_str,
            action_url=sanitize_text(action_url or "", 512) or None,
            due_at=due_at,
            notification_metadata=self._sanitize_meta(metadata),
        )
        notification_repository.prune_over_limit(db, recipient_user_id, self._max_per_user())
        self._write_audit(
            db,
            audit_actions.ACTION_NOTIFICATION_CREATED,
            account_id=account_id,
            project_id=project_id,
            user_id=recipient_user_id,
            metadata={
                "notification_id": notification.id,
                "notification_type": notification_type,
                "entity_type": entity_type,
                "entity_id": entity_id_str,
                "priority": priority,
            },
        )
        return self._view(notification)

    # ------------------------------------------------------------------ #
    # 2-6. Хуки (безопасны: не роняют основное действие)                  #
    # ------------------------------------------------------------------ #

    def notify_assignee(
        self, db: Session, task: Any, actor_user_id: int | None = None
    ) -> dict[str, Any] | None:
        """Уведомить назначенного ответственного (review_assigned)."""
        return self._safe(
            db,
            lambda: self._notify_task_user(
                db,
                task,
                recipient_user_id=getattr(task, "assignee_user_id", None),
                notification_type="review_assigned",
                title="Вам назначена задача ревью медиатеки",
                message=f"Задача #{task.id}: {getattr(task, 'title', '') or 'без названия'}",
                actor_user_id=actor_user_id,
            ),
        )

    def notify_comment(
        self, db: Session, task: Any, comment: Any, actor_user_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Уведомить ответственного/ревьюера о новом комментарии (кроме автора)."""

        def _run() -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            recipients = {
                getattr(task, "assignee_user_id", None),
                getattr(task, "reviewer_user_id", None),
            }
            recipients.discard(None)
            recipients.discard(actor_user_id)
            for uid in recipients:
                view = self._notify_task_user(
                    db,
                    task,
                    recipient_user_id=uid,
                    notification_type="review_comment",
                    title="Новый комментарий к задаче ревью",
                    message=sanitize_text(getattr(comment, "comment_text", "") or "Комментарий"),
                    actor_user_id=actor_user_id,
                )
                if view is not None:
                    out.append(view)
            return out

        return self._safe(db, _run) or []

    def notify_mentions(
        self,
        db: Session,
        source_entity_type: str,
        source_entity_id: str | int,
        text: str,
        project_id: int | None = None,
        account_id: int | None = None,
        actor_user_id: int | None = None,
        comment_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Разобрать упоминания, создать AppMention и уведомить резолвленных (unresolved — тихо)."""
        if not self._mention_enabled():
            return []

        def _run() -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            for raw in mentions.extract_mentions(text or ""):
                user = mentions.resolve_mention_to_user(db, account_id, raw)
                mention = notification_repository.create_mention(
                    db,
                    account_id=account_id,
                    project_id=project_id,
                    source_entity_type=source_entity_type,
                    source_entity_id=str(source_entity_id),
                    comment_id=comment_id,
                    mentioned_text=sanitize_text(raw, 255),
                    mentioned_user_id=user.id if user is not None else None,
                    status="resolved" if user is not None else "unresolved",
                )
                self._write_audit(
                    db,
                    audit_actions.ACTION_MENTION_CREATED,
                    account_id=account_id,
                    project_id=project_id,
                    user_id=user.id if user is not None else None,
                    metadata={
                        "mention_id": mention.id,
                        "status": mention.status,
                        "source_entity_type": source_entity_type,
                        "source_entity_id": str(source_entity_id),
                    },
                )
                if user is None or user.id == actor_user_id:
                    continue
                view = self.create_notification(
                    db,
                    recipient_user_id=user.id,
                    notification_type="review_mentioned",
                    title="Вас упомянули в комментарии",
                    message=sanitize_text(text or "", 500),
                    account_id=account_id,
                    project_id=project_id,
                    actor_user_id=actor_user_id,
                    entity_type=source_entity_type,
                    entity_id=source_entity_id,
                    priority="normal",
                    action_url=self._review_url(project_id, source_entity_id),
                )
                if view is not None:
                    notification_repository.resolve_mention(
                        db, mention, user.id, "notified", view.get("id")
                    )
                    self._write_audit(
                        db,
                        audit_actions.ACTION_MENTION_RESOLVED,
                        account_id=account_id,
                        project_id=project_id,
                        user_id=user.id,
                        metadata={"mention_id": mention.id, "notification_id": view.get("id")},
                    )
                    out.append(view)
            return out

        return self._safe(db, _run) or []

    def notify_project_owner(
        self,
        db: Session,
        project_id: int | None,
        notification_type: str,
        title: str,
        message: str,
        actor_user_id: int | None = None,
        entity_type: str | None = None,
        entity_id: str | int | None = None,
        priority: str = "normal",
        action_url: str | None = None,
    ) -> dict[str, Any] | None:
        """Уведомить владельца аккаунта проекта (skip если некому/сам инициатор). Безопасно."""

        def _run() -> dict[str, Any] | None:
            recipient = self._project_owner_id(db, project_id)
            if recipient is None or recipient == actor_user_id:
                return None
            return self.create_notification(
                db,
                recipient_user_id=recipient,
                notification_type=notification_type,
                title=title,
                message=message,
                account_id=self._account_id(db, project_id),
                project_id=project_id,
                actor_user_id=actor_user_id,
                entity_type=entity_type,
                entity_id=entity_id,
                priority=priority,
                action_url=action_url,
            )

        return self._safe(db, _run)

    def notify_status_change(
        self,
        db: Session,
        entity: Any,
        old_status: str,
        new_status: str,
        actor_user_id: int | None = None,
    ) -> dict[str, Any] | None:
        """Уведомить о смене статуса ревью (changes_requested/approved/rejected/applied)."""
        notification_type = _STATUS_NOTIFICATION_TYPE.get(new_status)
        if notification_type is None:
            return None
        return self._safe(
            db,
            lambda: self._notify_task_user(
                db,
                entity,
                recipient_user_id=getattr(entity, "assignee_user_id", None),
                notification_type=notification_type,
                title=f"Задача ревью: {new_status}",
                message=f"Задача #{entity.id} перешла в статус «{new_status}».",
                actor_user_id=actor_user_id,
            ),
        )

    def notify_overdue_tasks(
        self, db: Session, project_id: int | None = None, dry_run: bool = True
    ) -> dict[str, Any]:
        """Просканировать просроченные задачи ревью и (в write-режиме) создать task_overdue."""
        if not self._overdue_scan_enabled():
            return {
                "dry_run": dry_run,
                "overdue_found": 0,
                "notifications_created": 0,
                "enabled": False,
            }
        grace = timedelta(seconds=self._overdue_grace_seconds())
        ref = datetime.now(UTC) - grace
        project_ids = [project_id] if project_id is not None else self._all_project_ids(db)
        overdue: list[Any] = []
        for pid in project_ids:
            overdue.extend(review_repo.list_overdue_tasks(db, pid, ref=ref, limit=500))
        created = 0
        if dry_run:
            self._write_audit(
                db,
                audit_actions.ACTION_NOTIFICATION_OVERDUE_SCAN_PREVIEWED,
                project_id=project_id,
                metadata={"overdue_found": len(overdue)},
            )
        else:
            for task in overdue:
                view = self._notify_task_user(
                    db,
                    task,
                    recipient_user_id=getattr(task, "assignee_user_id", None)
                    or getattr(task, "reviewer_user_id", None),
                    notification_type="task_overdue",
                    title="Задача ревью просрочена",
                    message=f"Задача #{task.id} просрочена (приоритет {task.priority}).",
                    priority="high" if task.priority in ("high", "urgent") else "normal",
                )
                if view is not None:
                    created += 1
            self._write_audit(
                db,
                audit_actions.ACTION_NOTIFICATION_OVERDUE_SCAN_CREATED,
                project_id=project_id,
                metadata={"overdue_found": len(overdue), "notifications_created": created},
            )
        return {
            "dry_run": dry_run,
            "project_id": project_id,
            "overdue_found": len(overdue),
            "notifications_created": created,
            "enabled": True,
        }

    # ------------------------------------------------------------------ #
    # 7-9. Действия пользователя (могут падать → API-ошибки)              #
    # ------------------------------------------------------------------ #

    def mark_read(
        self, db: Session, notification_id: int, current_user_id: int | None
    ) -> dict[str, Any]:
        """Отметить прочитанным (только получатель)."""
        notification = self._owned(db, notification_id, current_user_id)
        notification_repository.mark_read(db, notification)
        self._write_audit(
            db,
            audit_actions.ACTION_NOTIFICATION_READ,
            account_id=notification.account_id,
            project_id=notification.project_id,
            user_id=current_user_id,
            metadata={"notification_id": notification.id},
        )
        return self._view(notification)

    def mark_all_read(
        self, db: Session, current_user_id: int | None, project_id: int | None = None
    ) -> dict[str, Any]:
        """Отметить все непрочитанные пользователя прочитанными."""
        if current_user_id is None:
            raise NotificationError("Требуется пользователь")
        count = notification_repository.mark_all_read(db, current_user_id, project_id)
        return {"marked_read": count}

    def dismiss(
        self, db: Session, notification_id: int, current_user_id: int | None
    ) -> dict[str, Any]:
        """Скрыть (dismiss) уведомление (только получатель)."""
        notification = self._owned(db, notification_id, current_user_id)
        notification_repository.dismiss_notification(db, notification)
        self._write_audit(
            db,
            audit_actions.ACTION_NOTIFICATION_DISMISSED,
            account_id=notification.account_id,
            project_id=notification.project_id,
            user_id=current_user_id,
            metadata={"notification_id": notification.id},
        )
        return self._view(notification)

    # ------------------------------------------------------------------ #
    # 10. Inbox                                                           #
    # ------------------------------------------------------------------ #

    def build_user_inbox(
        self,
        db: Session,
        user_id: int,
        status: str | None = None,
        notification_type: str | None = None,
        priority: str | None = None,
        project_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Inbox пользователя: список уведомлений + счётчик непрочитанных."""
        rows = notification_repository.list_for_user(
            db,
            user_id,
            status=status,
            notification_type=notification_type,
            priority=priority,
            project_id=project_id,
            limit=limit,
            offset=offset,
        )
        return {
            "user_id": user_id,
            "unread_count": notification_repository.count_unread_for_user(db, user_id),
            "count": len(rows),
            "notifications": [self._view(n) for n in rows],
        }

    def unread_count(self, db: Session, user_id: int) -> int:
        """Число непрочитанных уведомлений пользователя."""
        return notification_repository.count_unread_for_user(db, user_id)

    # ------------------------------------------------------------------ #
    # 11. Workload ревьюеров + SLA                                        #
    # ------------------------------------------------------------------ #

    def build_review_workload(self, db: Session, project_id: int | None = None) -> dict[str, Any]:
        """Нагрузка ревьюеров по задачам ревью медиатеки: assigned/overdue/high/urgent, SLA."""
        if project_id is None:
            return {"project_id": None, "reviewers": [], "unassigned_active": 0}
        tasks = media_curation_repository.list_tasks_for_project(db, project_id, limit=2000)
        now = datetime.now(UTC)
        sla_seconds = self._sla_seconds()
        by_user: dict[int, list[Any]] = {}
        unassigned = 0
        for t in tasks:
            if getattr(t, "review_status", "proposed") not in _ACTIVE_REVIEW_STATUSES:
                continue
            uid = t.assignee_user_id
            if uid is None:
                unassigned += 1
                continue
            by_user.setdefault(uid, []).append(t)
        reviewers: list[dict[str, Any]] = []
        for uid, items in by_user.items():
            overdue = sum(1 for t in items if self._is_overdue(t, now))
            high = sum(1 for t in items if t.priority in ("high", "urgent"))
            ages = [self._age_hours(t, now) for t in items]
            avg_age = round(sum(ages) / len(ages), 1) if ages else 0.0
            max_age_seconds = max((a * 3600 for a in ages), default=0.0)
            reviewers.append(
                {
                    "reviewer_user_id": uid,
                    "assigned_count": len(items),
                    "overdue_count": overdue,
                    "high_priority_count": high,
                    "avg_age_hours": avg_age,
                    "sla_status": self._sla_status(overdue, max_age_seconds, sla_seconds),
                }
            )
        reviewers.sort(key=lambda r: (r["overdue_count"], r["assigned_count"]), reverse=True)
        self._write_audit(
            db,
            audit_actions.ACTION_WORKLOAD_VIEWED,
            project_id=project_id,
            metadata={"reviewers": len(reviewers)},
        )
        return {
            "project_id": project_id,
            "reviewers": reviewers,
            "unassigned_active": unassigned,
            "sla_hours": int(sla_seconds / 3600),
        }

    # ------------------------------------------------------------------ #
    # 12. Дашборд уведомлений проекта                                     #
    # ------------------------------------------------------------------ #

    def build_project_notification_dashboard(self, db: Session, project_id: int) -> dict[str, Any]:
        """Сводка уведомлений проекта: непрочитанные, overdue, по типу, high/urgent."""
        summary = notification_repository.get_dashboard_summary(db, project_id)
        by_priority = summary["by_priority"]
        return {
            "project_id": project_id,
            "total": summary["total"],
            "unread": summary["by_status"].get("unread", 0),
            "read": summary["by_status"].get("read", 0),
            "dismissed": summary["by_status"].get("dismissed", 0),
            "overdue": summary["by_type"].get("task_overdue", 0),
            "high_priority": by_priority.get("high", 0) + by_priority.get("urgent", 0),
            "by_type": summary["by_type"],
            "by_priority": by_priority,
            "external_delivery_enabled": self._external_delivery_enabled(),
        }

    # --- Упоминания (чтение) --- #

    def list_project_mentions(
        self, db: Session, project_id: int, status: str | None = None
    ) -> list[dict[str, Any]]:
        """Упоминания проекта (для дашборда)."""
        rows = notification_repository.list_mentions_for_project(db, project_id, status=status)
        return [self._mention_view(m) for m in rows]

    # --- Настройки --- #

    def get_preferences(
        self, db: Session, user_id: int, account_id: int | None = None
    ) -> dict[str, Any]:
        """Настройки уведомлений пользователя + безопасные дефолты каналов."""
        rows = notification_repository.get_preferences(db, user_id, account_id)
        return {
            "user_id": user_id,
            "in_app_enabled": self._in_app_enabled(),
            "email_enabled": False,
            "digest_enabled": False,
            "webhook_enabled": False,
            "external_delivery_enabled": self._external_delivery_enabled(),
            "preferences": [self._preference_view(p) for p in rows],
        }

    def set_preference(
        self,
        db: Session,
        user_id: int,
        channel: str,
        enabled: bool,
        notification_type: str | None = None,
        account_id: int | None = None,
    ) -> dict[str, Any]:
        """Задать настройку уведомления. Внешние каналы нельзя включить, пока нет доставки."""
        if channel not in ("in_app", "email", "digest", "webhook"):
            raise NotificationError(f"Неизвестный канал: {channel}")
        # Внешние каналы принудительно выключены, пока внешняя доставка отключена.
        if channel != "in_app" and not self._external_delivery_enabled():
            enabled = False
        pref = notification_repository.set_preference(
            db, user_id, channel, enabled, notification_type, account_id
        )
        self._write_audit(
            db,
            audit_actions.ACTION_NOTIFICATION_PREFERENCE_UPDATED,
            account_id=account_id,
            user_id=user_id,
            metadata={
                "channel": channel,
                "notification_type": notification_type,
                "enabled": enabled,
            },
        )
        return self._preference_view(pref)

    # ------------------------------------------------------------------ #
    # Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    def _notify_task_user(
        self,
        db: Session,
        task: Any,
        recipient_user_id: int | None,
        notification_type: str,
        title: str,
        message: str,
        actor_user_id: int | None = None,
        priority: str | None = None,
    ) -> dict[str, Any] | None:
        if recipient_user_id is None or recipient_user_id == actor_user_id:
            return None
        project_id = getattr(task, "project_id", None)
        account_id = self._account_id(db, project_id) if project_id is not None else None
        return self.create_notification(
            db,
            recipient_user_id=recipient_user_id,
            notification_type=notification_type,
            title=title,
            message=message,
            account_id=account_id,
            project_id=project_id,
            actor_user_id=actor_user_id,
            entity_type="media_curation_task",
            entity_id=task.id,
            priority=priority or getattr(task, "priority", "normal") or "normal",
            due_at=getattr(task, "due_at", None),
            action_url=self._review_url(project_id, task.id),
        )

    def _owned(
        self, db: Session, notification_id: int, current_user_id: int | None
    ) -> AppNotification:
        notification = notification_repository.get_notification_by_id(db, notification_id)
        if notification is None:
            raise NotificationError("Уведомление не найдено")
        if current_user_id is None or notification.recipient_user_id != current_user_id:
            raise NotificationError("Нет доступа к уведомлению")
        return notification

    @staticmethod
    def _review_url(project_id: int | None, task_id: int | str) -> str | None:
        if project_id is None:
            return None
        return f"/ui/projects/{project_id}/media-curation-review/tasks/{task_id}"

    def _is_overdue(self, task: Any, now: datetime) -> bool:
        due = getattr(task, "due_at", None)
        if due is None or getattr(task, "review_status", None) not in _ACTIVE_REVIEW_STATUSES:
            return False
        if due.tzinfo is None:
            due = due.replace(tzinfo=UTC)
        return bool(due < now)

    @staticmethod
    def _age_hours(task: Any, now: datetime) -> float:
        created = getattr(task, "created_at", None)
        if created is None:
            return 0.0
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        return float(max(0.0, (now - created).total_seconds() / 3600.0))

    @staticmethod
    def _sla_status(overdue: int, max_age_seconds: float, sla_seconds: int) -> str:
        if overdue >= 3:
            return "critical"
        if overdue > 0:
            return "overdue"
        if max_age_seconds >= sla_seconds * 0.75:
            return "due_soon"
        return "ok"

    def _all_project_ids(self, db: Session) -> list[int]:
        return [p.id for p in project_repository.list_projects(db)]

    def _account_id(self, db: Session, project_id: int | None) -> int | None:
        if project_id is None:
            return None
        project = project_repository.get_project_by_id(db, project_id)
        return project.account_id if project is not None else None

    def _project_owner_id(self, db: Session, project_id: int | None) -> int | None:
        """Резолвить получателя по умолчанию: владелец аккаунта проекта (или None)."""
        account_id = self._account_id(db, project_id)
        if account_id is None:
            return None
        account = account_repository.get_account_by_id(db, account_id)
        return account.owner_user_id if account is not None else None

    def _sanitize_meta(self, metadata: dict[str, Any] | None) -> dict[str, Any]:
        if not metadata:
            return {}
        cleaned = sanitize_metadata(metadata)
        return cleaned if isinstance(cleaned, dict) else {}

    # --- Views ---

    def _view(self, n: AppNotification) -> dict[str, Any]:
        return {
            "id": n.id,
            "project_id": n.project_id,
            "recipient_user_id": n.recipient_user_id,
            "actor_user_id": n.actor_user_id,
            "notification_type": n.notification_type,
            "channel": n.channel,
            "status": n.status,
            "priority": n.priority,
            "title": n.title,
            "message": n.message,
            "entity_type": n.entity_type,
            "entity_id": n.entity_id,
            "action_url": n.action_url,
            "due_at": n.due_at.isoformat() if n.due_at else None,
            "read_at": n.read_at.isoformat() if n.read_at else None,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }

    @staticmethod
    def _mention_view(m: AppMention) -> dict[str, Any]:
        return {
            "id": m.id,
            "project_id": m.project_id,
            "source_entity_type": m.source_entity_type,
            "source_entity_id": m.source_entity_id,
            "mentioned_text": m.mentioned_text,
            "mentioned_user_id": m.mentioned_user_id,
            "status": m.status,
            "notification_id": m.notification_id,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }

    @staticmethod
    def _preference_view(p: NotificationPreference) -> dict[str, Any]:
        return {
            "id": p.id,
            "channel": p.channel,
            "notification_type": p.notification_type,
            "enabled": p.enabled,
            "digest_frequency": p.digest_frequency,
        }

    # --- safety wrapper ---

    def _safe(self, db: Session, fn: Callable[[], _R]) -> _R | None:
        """Выполнить hook-функцию, проглатывая ошибки (уведомления не роняют действие)."""
        try:
            return fn()
        except Exception:  # noqa: BLE001 — уведомления не критичны для основного действия
            logger.warning("notification hook failed", exc_info=False)
            import contextlib

            with contextlib.suppress(Exception):
                db.rollback()
            return None

    # --- settings/deps ---

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _enabled(self) -> bool:
        return bool(self._resolve_settings().notifications_enabled_effective)

    def _in_app_enabled(self) -> bool:
        return bool(self._resolve_settings().notifications_in_app_enabled_effective)

    def _external_delivery_enabled(self) -> bool:
        return bool(self._resolve_settings().notifications_external_delivery_enabled_effective)

    def _mention_enabled(self) -> bool:
        s = self._resolve_settings()
        return bool(s.notifications_enabled and s.notifications_mention_enabled)

    def _overdue_scan_enabled(self) -> bool:
        s = self._resolve_settings()
        return bool(s.notifications_enabled and s.notifications_overdue_scan_enabled)

    def _dedup_seconds(self) -> int:
        return int(self._resolve_settings().notifications_dedup_window_seconds)

    def _overdue_grace_seconds(self) -> int:
        return int(self._resolve_settings().notifications_overdue_grace_seconds)

    def _max_per_user(self) -> int:
        return int(self._resolve_settings().notifications_max_per_user_safe)

    def _sla_seconds(self) -> int:
        return int(self._resolve_settings().media_curation_review_sla_seconds)

    def _audit_svc(self) -> AuditLogService:
        if self._audit is None:
            from app.services.audit_log_service import AuditLogService

            self._audit = AuditLogService()
        return self._audit

    def _write_audit(
        self,
        db: Session,
        action: str,
        account_id: int | None = None,
        project_id: int | None = None,
        user_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._audit_svc().record(
            db,
            action,
            account_id=account_id,
            project_id=project_id,
            user_id=user_id,
            entity_type="notification",
            metadata=self._sanitize_meta(metadata),
        )


def get_notification_service() -> NotificationService:
    """DI-фабрика сервиса уведомлений."""
    return NotificationService()
