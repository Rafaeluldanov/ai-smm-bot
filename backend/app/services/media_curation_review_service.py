"""Collaborative review курирования медиатеки (v0.4.9).

Медиатека курируется через нормальный workflow: задачи на проверку, ответственные,
комментарии, история решений, кто одобрил/отклонил/применил. Изменения (теги/видимость)
применяются ТОЛЬКО после ``approved``; файлы НЕ удаляются; внешнего AI нет; live-публикаций/
платежей нет; авто-применение и уведомления выключены по умолчанию.

БЕЗОПАСНОСТЬ:
- комментарии/метаданные санитизируются (без секретов и внутренних путей к файлам);
- строгая project/account-изоляция (гарды на API-слое);
- double-apply запрещён; нет удаления медиа/файлов.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.redaction import redact_sensitive_text
from app.models.media_curation_task import (
    MEDIA_CURATION_APPROVAL_REQUIRED_ACTIONS,
    MEDIA_CURATION_COMMENT_TYPES,
    MEDIA_CURATION_PRIORITIES,
)
from app.repositories import (
    media_asset_repository,
    media_curation_repository,
    project_repository,
)
from app.repositories import (
    media_curation_review_repository as review_repo,
)
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:
    from app.config import Settings
    from app.models.media_curation_comment import MediaCurationComment
    from app.models.media_curation_task import MediaCurationTask
    from app.services.audit_log_service import AuditLogService
    from app.services.media_curation_service import MediaCurationService
    from app.services.notification_service import NotificationService

logger = get_logger(__name__)

# Внутренние пути к файлам (disk:/…, абсолютные пути) — не должны попадать в комментарии.
_INTERNAL_PATH_RE = re.compile(
    r"(?i)(?:disk:/\S+|/(?:Users|home|var|etc|tmp|mnt|srv|opt|root)/\S+|[A-Za-z]:\\\S+)"
)

_ACTIVE_REVIEW_STATUSES = ("proposed", "assigned", "in_review", "changes_requested", "approved")


def sanitize_review_text(text: str) -> str:
    """Очистить текст комментария от секретов и внутренних путей (без физического удаления)."""
    cleaned = redact_sensitive_text(text or "")
    cleaned = _INTERNAL_PATH_RE.sub("[путь скрыт]", cleaned)
    return cleaned.strip()[:4000]


class MediaCurationReviewError(Exception):
    """Ошибка workflow ревью (нет задачи/проекта, лимит комментариев) — API → 400."""


class MediaCurationReviewService:
    """Workflow согласования медиатеки: задачи, ответственные, комментарии, история, apply."""

    def __init__(
        self,
        curation_service: MediaCurationService | None = None,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
        notification_service: NotificationService | None = None,
    ) -> None:
        self._curation = curation_service
        self._audit = audit_service
        self._settings = settings
        self._notifications = notification_service

    # ------------------------------------------------------------------ #
    # 1. Список задач ревью                                               #
    # ------------------------------------------------------------------ #

    def list_review_tasks(
        self,
        db: Session,
        project_id: int,
        review_status: str | None = None,
        priority: str | None = None,
        assignee_user_id: int | None = None,
        task_type: str | None = None,
        overdue: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Задачи проекта для доски ревью (по фильтрам)."""
        rows = review_repo.list_review_tasks(
            db,
            project_id,
            review_status=review_status,
            priority=priority,
            assignee_user_id=assignee_user_id,
            task_type=task_type,
            overdue=overdue,
            limit=limit,
            offset=offset,
        )
        return [self._task_view(t) for t in rows]

    # ------------------------------------------------------------------ #
    # 2. Детали задачи (task + comments + timeline + before/after)        #
    # ------------------------------------------------------------------ #

    def get_task_detail(self, db: Session, project_id: int | None, task_id: int) -> dict[str, Any]:
        """Полные детали задачи ревью: задача, комментарии, timeline, before/after, safety."""
        task = self._get_task(db, project_id, task_id)
        comments = review_repo.list_comments_for_task(db, task_id, limit=500)
        timeline = review_repo.build_review_timeline(db, task)
        return {
            "task": self._task_view(task),
            "comments": [self._comment_view(c) for c in comments],
            "timeline": timeline,
            "suggested_action": task.suggested_action,
            "before_state": dict(task.before_state or {}),
            "after_state": dict(task.after_state or {}),
            "decision_summary": dict(task.decision_summary or {}),
            "is_overdue": self._is_overdue(task),
            "safety_notes": [
                "Файлы не удаляются — меняются только теги и видимость.",
                "Изменения применяются только после подтверждения (approved).",
                "Без внешнего AI; live-публикаций и реальных платежей нет.",
            ],
        }

    # ------------------------------------------------------------------ #
    # 3. Комментарии                                                      #
    # ------------------------------------------------------------------ #

    def add_comment(
        self,
        db: Session,
        task_id: int,
        comment_text: str,
        current_user_id: int | None = None,
        comment_type: str = "comment",
        project_id: int | None = None,
    ) -> dict[str, Any]:
        """Добавить комментарий к задаче (санитизация; аудит; без секретов)."""
        task = self._get_task(db, project_id, task_id)
        if comment_type not in MEDIA_CURATION_COMMENT_TYPES:
            comment_type = "comment"
        if review_repo.count_comments_for_task(db, task_id) >= self._max_comments():
            raise MediaCurationReviewError("Достигнут лимит комментариев на задачу")
        cleaned = sanitize_review_text(comment_text)
        if not cleaned:
            raise MediaCurationReviewError("Пустой комментарий")
        comment = review_repo.create_comment(
            db,
            project_id=task.project_id,
            task_id=task.id,
            account_id=self._account_id(db, task.project_id),
            user_id=current_user_id,
            comment_text=cleaned,
            comment_type=comment_type,
        )
        self._write_audit(
            db,
            task,
            audit_actions.ACTION_MEDIA_CURATION_REVIEW_COMMENT_ADDED,
            current_user_id,
            {"comment_id": comment.id, "comment_type": comment_type},
        )
        # Уведомления (безопасно; не роняют комментарий): ответственный/ревьюер + упоминания.
        self._notify().notify_comment(db, task, comment, current_user_id)
        self._notify().notify_mentions(
            db,
            "media_curation_task",
            task.id,
            comment_text,
            project_id=task.project_id,
            account_id=self._account_id(db, task.project_id),
            actor_user_id=current_user_id,
            comment_id=comment.id,
        )
        return self._comment_view(comment)

    def list_comments(
        self, db: Session, project_id: int | None, task_id: int, limit: int = 200, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Комментарии задачи (хронология обсуждения)."""
        task = self._get_task(db, project_id, task_id)
        rows = review_repo.list_comments_for_task(db, task.id, limit=limit, offset=offset)
        return [self._comment_view(c) for c in rows]

    # ------------------------------------------------------------------ #
    # 4-5. Назначение / старт ревью                                       #
    # ------------------------------------------------------------------ #

    def assign_task(
        self,
        db: Session,
        task_id: int,
        assignee_user_id: int,
        current_user_id: int | None = None,
        priority: str | None = None,
        due_at: datetime | None = None,
        project_id: int | None = None,
    ) -> dict[str, Any]:
        """Назначить ответственного (assigned) + опционально приоритет/срок; система-комментарий."""
        task = self._get_task(db, project_id, task_id)
        review_repo.assign_task(db, task, assignee_user_id, current_user_id)
        if priority is not None and priority in MEDIA_CURATION_PRIORITIES:
            review_repo.set_priority(db, task, priority, current_user_id)
        if due_at is not None:
            review_repo.set_due_at(db, task, due_at, current_user_id)
        self._system_comment(
            db, task, f"Назначен ответственный (пользователь #{assignee_user_id}).", current_user_id
        )
        self._write_audit(
            db,
            task,
            audit_actions.ACTION_MEDIA_CURATION_REVIEW_ASSIGNED,
            current_user_id,
            {"assignee_user_id": assignee_user_id},
        )
        self._notify().notify_assignee(db, task, current_user_id)
        return {**self._task_view(task), "outcome": "assigned"}

    def set_priority(
        self,
        db: Session,
        task_id: int,
        priority: str,
        current_user_id: int | None = None,
        project_id: int | None = None,
    ) -> dict[str, Any]:
        """Задать приоритет задачи (low|normal|high|urgent)."""
        if priority not in MEDIA_CURATION_PRIORITIES:
            raise MediaCurationReviewError(f"Недопустимый приоритет: {priority}")
        task = self._get_task(db, project_id, task_id)
        review_repo.set_priority(db, task, priority, current_user_id)
        return {**self._task_view(task), "outcome": "priority_set"}

    def set_due_at(
        self,
        db: Session,
        task_id: int,
        due_at: datetime | None,
        current_user_id: int | None = None,
        project_id: int | None = None,
    ) -> dict[str, Any]:
        """Задать срок задачи (due_at)."""
        task = self._get_task(db, project_id, task_id)
        review_repo.set_due_at(db, task, due_at, current_user_id)
        return {**self._task_view(task), "outcome": "due_set"}

    def start_review(
        self,
        db: Session,
        task_id: int,
        current_user_id: int | None = None,
        project_id: int | None = None,
    ) -> dict[str, Any]:
        """Начать проверку: in_review, зафиксировать reviewer."""
        task = self._get_task(db, project_id, task_id)
        review_repo.mark_in_review(db, task, current_user_id)
        self._system_comment(db, task, "Начата проверка (in_review).", current_user_id)
        self._write_audit(
            db, task, audit_actions.ACTION_MEDIA_CURATION_REVIEW_STARTED, current_user_id, {}
        )
        return {**self._task_view(task), "outcome": "in_review"}

    # ------------------------------------------------------------------ #
    # 6. Запрос правок                                                    #
    # ------------------------------------------------------------------ #

    def request_changes(
        self,
        db: Session,
        task_id: int,
        comment: str | None = None,
        current_user_id: int | None = None,
        project_id: int | None = None,
    ) -> dict[str, Any]:
        """Запросить правки: changes_requested + комментарий (request_changes)."""
        task = self._get_task(db, project_id, task_id)
        review_repo.mark_changes_requested(db, task, current_user_id)
        text = sanitize_review_text(comment or "Требуются правки.")
        self._add_typed_comment(db, task, text, current_user_id, "request_changes")
        self._write_audit(
            db,
            task,
            audit_actions.ACTION_MEDIA_CURATION_REVIEW_CHANGES_REQUESTED,
            current_user_id,
            {},
        )
        self._notify().notify_status_change(
            db, task, "in_review", "changes_requested", current_user_id
        )
        return {**self._task_view(task), "outcome": "changes_requested"}

    # ------------------------------------------------------------------ #
    # 7. Одобрение                                                        #
    # ------------------------------------------------------------------ #

    def approve_task(
        self,
        db: Session,
        task_id: int,
        comment: str | None = None,
        current_user_id: int | None = None,
        project_id: int | None = None,
    ) -> dict[str, Any]:
        """Одобрить задачу (approved). Не применяет автоматически (если не включён auto-apply)."""
        task = self._get_task(db, project_id, task_id)
        if not self._allow_self_approval() and (
            current_user_id is not None and current_user_id == task.assignee_user_id
        ):
            return {
                **self._task_view(task),
                "outcome": "blocked",
                "reason": "self_approval_disabled",
            }
        review_repo.mark_approved(db, task, current_user_id)
        if comment:
            self._add_typed_comment(
                db, task, sanitize_review_text(comment), current_user_id, "approval"
            )
        self._write_audit(
            db, task, audit_actions.ACTION_MEDIA_CURATION_REVIEW_APPROVED, current_user_id, {}
        )
        self._notify().notify_status_change(db, task, "in_review", "approved", current_user_id)
        result = {**self._task_view(task), "outcome": "approved", "auto_applied": False}
        # Авто-применение после approve выключено по умолчанию (безопасно).
        if self._auto_apply_after_approval() and task.suggested_action in (
            MEDIA_CURATION_APPROVAL_REQUIRED_ACTIONS
        ):
            applied = self.apply_approved_task(
                db, task_id, task.suggested_action, current_user_id, project_id=task.project_id
            )
            result = {**applied, "outcome": "approved", "auto_applied": True}
        return result

    # ------------------------------------------------------------------ #
    # 8. Отклонение                                                       #
    # ------------------------------------------------------------------ #

    def reject_task(
        self,
        db: Session,
        task_id: int,
        reason: str | None = None,
        current_user_id: int | None = None,
        project_id: int | None = None,
    ) -> dict[str, Any]:
        """Отклонить задачу (rejected). Изменения НЕ применяются."""
        task = self._get_task(db, project_id, task_id)
        review_repo.mark_rejected(db, task, current_user_id)
        text = sanitize_review_text(reason or "Отклонено.")
        self._add_typed_comment(db, task, text, current_user_id, "rejection")
        self._write_audit(
            db, task, audit_actions.ACTION_MEDIA_CURATION_REVIEW_REJECTED, current_user_id, {}
        )
        self._notify().notify_status_change(db, task, "in_review", "rejected", current_user_id)
        return {**self._task_view(task), "outcome": "rejected"}

    # ------------------------------------------------------------------ #
    # 9. Применение одобренной задачи                                     #
    # ------------------------------------------------------------------ #

    def apply_approved_task(
        self,
        db: Session,
        task_id: int,
        action: str,
        current_user_id: int | None = None,
        project_id: int | None = None,
    ) -> dict[str, Any]:
        """Применить изменения одобренной задачи (approve_tags/mark_duplicate/hide/…).

        Гейт: изменяющие медиа действия — только после approved. Double-apply запрещён.
        Записывает before/after и decision_summary. Файлы не удаляются.
        """
        task = self._get_task(db, project_id, task_id)
        if task.review_status == "applied" or task.status == "applied":
            return {**self._task_view(task), "outcome": "already_applied", "blocked": True}
        requires_approval = action in MEDIA_CURATION_APPROVAL_REQUIRED_ACTIONS
        if requires_approval and self._require_approval() and task.review_status != "approved":
            return {
                **self._task_view(task),
                "outcome": "requires_approval",
                "blocked": True,
            }
        before_state = self._capture_media_state(db, task)
        try:
            result = self._curation_service().apply_task(db, task_id, action, current_user_id)
        except Exception:
            logger.warning("media curation review apply failed task_id=%s", task_id)
            db.rollback()
            raise
        outcome = result.get("outcome")
        if outcome in ("requires_approval", "already_final"):
            return {**self._task_view(task), "outcome": outcome, "blocked": True}
        db.refresh(task)
        after_state = self._capture_media_state(db, task)
        decision_summary = {
            "action": action,
            "outcome": outcome,
            "task_type": task.task_type,
            "applied_by_user_id": current_user_id,
        }
        review_repo.mark_applied(
            db,
            task,
            current_user_id,
            before_state=before_state,
            after_state=after_state,
            decision_summary=decision_summary,
        )
        self._system_comment(
            db,
            task,
            f"Изменения применены (действие: {action}). Файлы не удаляются.",
            current_user_id,
        )
        self._write_audit(
            db,
            task,
            audit_actions.ACTION_MEDIA_CURATION_REVIEW_APPLIED,
            current_user_id,
            {"action": action, "outcome": outcome},
        )
        self._notify().notify_status_change(db, task, "approved", "applied", current_user_id)
        return {**self._task_view(task), "outcome": "applied", "action": action}

    # ------------------------------------------------------------------ #
    # 10-11. Игнор / восстановление                                       #
    # ------------------------------------------------------------------ #

    def ignore_task(
        self,
        db: Session,
        task_id: int,
        current_user_id: int | None = None,
        project_id: int | None = None,
    ) -> dict[str, Any]:
        """Проигнорировать задачу (ignored). Изменения НЕ применяются."""
        task = self._get_task(db, project_id, task_id)
        review_repo.mark_ignored(db, task, current_user_id)
        self._write_audit(
            db, task, audit_actions.ACTION_MEDIA_CURATION_REVIEW_IGNORED, current_user_id, {}
        )
        return {**self._task_view(task), "outcome": "ignored"}

    def restore_task_media(
        self,
        db: Session,
        task_id: int,
        current_user_id: int | None = None,
        project_id: int | None = None,
    ) -> dict[str, Any]:
        """Вернуть затронутые медиа в подбор (restore). Файлы не трогаем."""
        task = self._get_task(db, project_id, task_id)
        restored: list[int] = []
        ids = list(task.affected_media_asset_ids or [])
        if task.media_asset_id and task.media_asset_id not in ids:
            ids = [task.media_asset_id, *ids]
        for mid in ids:
            asset = media_asset_repository.get_media_asset_by_id(db, mid)
            if asset is None or asset.project_id != task.project_id:
                continue
            if asset.selection_visibility != "selectable":
                media_curation_repository.restore_media_visibility(db, mid)
                restored.append(mid)
        review_repo.mark_restored(db, task, current_user_id)
        self._system_comment(
            db, task, f"Медиа возвращено в подбор: {restored or 'нет изменений'}.", current_user_id
        )
        self._write_audit(
            db,
            task,
            audit_actions.ACTION_MEDIA_CURATION_REVIEW_RESTORED,
            current_user_id,
            {"restored_media_asset_ids": restored},
        )
        self._notify().notify_assignee(db, task, current_user_id)
        return {
            **self._task_view(task),
            "outcome": "restored",
            "restored_media_asset_ids": restored,
        }

    # ------------------------------------------------------------------ #
    # 12. Дашборд ревью                                                   #
    # ------------------------------------------------------------------ #

    def build_review_dashboard(
        self, db: Session, project_id: int, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """Сводка доски ревью: счётчики по статусам/приоритетам, overdue, мои задачи."""
        tasks = media_curation_repository.list_tasks_for_project(db, project_id, limit=2000)
        by_status: dict[str, int] = {}
        by_priority: dict[str, int] = {}
        for t in tasks:
            rs = getattr(t, "review_status", "proposed")
            by_status[rs] = by_status.get(rs, 0) + 1
            by_priority[t.priority] = by_priority.get(t.priority, 0) + 1
        overdue = review_repo.list_overdue_tasks(db, project_id, limit=500)
        for t in overdue:
            self._write_audit(db, t, audit_actions.ACTION_MEDIA_CURATION_REVIEW_OVERDUE, None, {})
        active = sum(by_status.get(s, 0) for s in _ACTIVE_REVIEW_STATUSES)
        my_tasks = 0
        if current_user_id is not None:
            my_tasks = len(review_repo.list_tasks_for_assignee(db, project_id, current_user_id))
        settings = self._resolve_settings()
        return {
            "project_id": project_id,
            "total_tasks": len(tasks),
            "active_review_tasks": active,
            "proposed": by_status.get("proposed", 0),
            "assigned": by_status.get("assigned", 0),
            "in_review": by_status.get("in_review", 0),
            "changes_requested": by_status.get("changes_requested", 0),
            "approved": by_status.get("approved", 0),
            "applied": by_status.get("applied", 0),
            "rejected": by_status.get("rejected", 0),
            "ignored": by_status.get("ignored", 0),
            "restored": by_status.get("restored", 0),
            "expired": by_status.get("expired", 0),
            "overdue": len(overdue),
            "by_status": by_status,
            "by_priority": by_priority,
            "my_tasks": my_tasks,
            "review_enabled": bool(settings.media_curation_review_enabled_effective),
            "require_approval": bool(settings.media_curation_review_require_approval_effective),
            "auto_apply_after_approval": bool(
                settings.media_curation_review_auto_apply_after_approval
            ),
            "notify_enabled": bool(settings.media_curation_review_notify_enabled),
            "external_ai_enabled": bool(settings.media_curation_review_external_ai_enabled),
        }

    # ------------------------------------------------------------------ #
    # Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    def _get_task(self, db: Session, project_id: int | None, task_id: int) -> MediaCurationTask:
        task = media_curation_repository.get_task_by_id(db, task_id)
        if task is None:
            raise MediaCurationReviewError("Задача не найдена")
        if project_id is not None and task.project_id != project_id:
            raise MediaCurationReviewError("Задача не принадлежит проекту")
        return task

    def _capture_media_state(self, db: Session, task: MediaCurationTask) -> dict[str, Any]:
        ids = list(task.affected_media_asset_ids or [])
        if task.media_asset_id and task.media_asset_id not in ids:
            ids = [task.media_asset_id, *ids]
        media: dict[str, Any] = {}
        for mid in ids:
            asset = media_asset_repository.get_media_asset_by_id(db, mid)
            if asset is None or asset.project_id != task.project_id:
                continue
            media[str(mid)] = {
                "tags": {k: list(v or []) for k, v in dict(asset.tags or {}).items()},
                "selection_visibility": asset.selection_visibility,
                "curation_status": asset.curation_status,
            }
        return {"media": media}

    def _is_overdue(self, task: MediaCurationTask) -> bool:
        if task.due_at is None or task.review_status not in _ACTIVE_REVIEW_STATUSES:
            return False
        due = task.due_at
        if due.tzinfo is None:
            due = due.replace(tzinfo=UTC)
        return due < datetime.now(UTC)

    def _system_comment(
        self, db: Session, task: MediaCurationTask, text: str, user_id: int | None
    ) -> None:
        self._add_typed_comment(db, task, sanitize_review_text(text), user_id, "system")

    def _add_typed_comment(
        self,
        db: Session,
        task: MediaCurationTask,
        text: str,
        user_id: int | None,
        comment_type: str,
    ) -> None:
        if review_repo.count_comments_for_task(db, task.id) >= self._max_comments():
            return  # мягкий предел — системные комментарии не роняют действие
        review_repo.create_comment(
            db,
            project_id=task.project_id,
            task_id=task.id,
            account_id=self._account_id(db, task.project_id),
            user_id=user_id,
            comment_text=sanitize_review_text(text),
            comment_type=comment_type,
        )

    def _task_view(self, task: MediaCurationTask) -> dict[str, Any]:
        view = self._curation_service()._task_view(task)
        view["is_overdue"] = self._is_overdue(task)
        return view

    @staticmethod
    def _comment_view(comment: MediaCurationComment) -> dict[str, Any]:
        # Только безопасные поля (текст уже санитизирован при создании).
        return {
            "id": comment.id,
            "task_id": comment.task_id,
            "user_id": comment.user_id,
            "comment_type": comment.comment_type,
            "comment_text": comment.comment_text,
            "created_at": comment.created_at.isoformat() if comment.created_at else None,
        }

    def _account_id(self, db: Session, project_id: int) -> int | None:
        project = project_repository.get_project_by_id(db, project_id)
        return project.account_id if project is not None else None

    def _write_audit(
        self,
        db: Session,
        task: MediaCurationTask,
        action: str,
        user_id: int | None,
        extra: dict[str, Any],
    ) -> None:
        metadata = {
            "task_id": task.id,
            "media_asset_id": task.media_asset_id,
            "action": action,
            "review_status": task.review_status,
            "priority": task.priority,
            **extra,
        }
        self._audit_svc().record(
            db,
            action,
            account_id=self._account_id(db, task.project_id),
            project_id=task.project_id,
            user_id=user_id,
            entity_type="media_curation_task",
            entity_id=task.id,
            metadata=metadata,
        )

    # --- Настройки / зависимости ---

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _require_approval(self) -> bool:
        return bool(self._resolve_settings().media_curation_review_require_approval_effective)

    def _allow_self_approval(self) -> bool:
        return bool(self._resolve_settings().media_curation_review_allow_self_approval)

    def _auto_apply_after_approval(self) -> bool:
        return bool(self._resolve_settings().media_curation_review_auto_apply_after_approval)

    def _max_comments(self) -> int:
        return int(self._resolve_settings().media_curation_review_max_comments_per_task_safe)

    def _curation_service(self) -> MediaCurationService:
        if self._curation is None:
            from app.services.media_curation_service import MediaCurationService

            self._curation = MediaCurationService(settings=self._settings)
        return self._curation

    def _audit_svc(self) -> AuditLogService:
        if self._audit is None:
            from app.services.audit_log_service import AuditLogService

            self._audit = AuditLogService()
        return self._audit

    def _notify(self) -> NotificationService:
        if self._notifications is None:
            from app.services.notification_service import NotificationService

            self._notifications = NotificationService(settings=self._settings)
        return self._notifications


def get_media_curation_review_service() -> MediaCurationReviewService:
    """DI-фабрика сервиса collaborative review курирования медиатеки."""
    return MediaCurationReviewService()
