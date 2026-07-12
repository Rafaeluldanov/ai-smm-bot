"""Курирование медиатеки (media library curation) — v0.4.8.

Botfleet предлагает клиенту задачи очистки/разметки медиатеки (проверить дубли, подтвердить
теги, скрыть дубль, заменить слабое медиа) и применяет их ТОЛЬКО после подтверждения. Файлы
НЕ удаляются; внешнего AI нет; авто-применение/скрытие/удаление выключены по умолчанию.

БЕЗОПАСНОСТЬ:
- никаких внешних AI/vision-вызовов и live-публикаций; удаления файлов нет;
- строгая project/account-изоляция; без секретов и внутренних путей к файлам в ответах;
- меняются только теги (после approve) и видимость (hidden/selectable) — не сам файл.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.media_curation_task import MEDIA_CURATION_APPROVAL_REQUIRED_ACTIONS
from app.repositories import (
    media_asset_repository,
    media_curation_repository,
    media_duplicate_cluster_repository,
    media_quality_repository,
    project_repository,
)
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:
    from app.config import Settings
    from app.services.audit_log_service import AuditLogService
    from app.services.media_tag_suggestion_service import MediaTagSuggestionService

logger = get_logger(__name__)

_USABLE_STATUSES = ("approved", "approved_video")
_HIDDEN_VISIBILITIES = ("hidden_duplicate", "hidden_weak", "hidden_manual", "archived")


class MediaCurationError(Exception):
    """Ошибка курирования (нет проекта/задачи/медиа) — API → 400."""


class MediaCurationService:
    """Задачи курирования медиатеки + применение только после подтверждения (без удаления)."""

    def __init__(
        self,
        tag_service: MediaTagSuggestionService | None = None,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._tags = tag_service
        self._audit = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # 1-2. Preview / генерация задач                                      #
    # ------------------------------------------------------------------ #

    def preview_curation_tasks(
        self,
        db: Session,
        project_id: int,
        platform_key: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Предпросмотр предлагаемых задач курирования (без записи)."""
        payloads = self._collect_task_payloads(db, project_id, platform_key)
        cap = self._max_tasks() if limit is None else min(int(limit), self._max_tasks())
        payloads = payloads[:cap]
        self._write_audit(
            db,
            project_id,
            audit_actions.ACTION_MEDIA_CURATION_PREVIEWED,
            {"platform_key": platform_key, "tasks": len(payloads)},
        )
        return {
            "project_id": project_id,
            "platform_key": platform_key,
            "dry_run": True,
            "tasks_found": len(payloads),
            "tasks": [self._payload_view(p) for p in payloads],
        }

    def generate_curation_tasks(
        self,
        db: Session,
        project_id: int,
        platform_key: str | None = None,
        dry_run: bool = True,
        idempotency_prefix: str | None = None,
        current_user_id: int | None = None,  # noqa: ARG002 — единый интерфейс
    ) -> dict[str, Any]:
        """Создать задачи курирования (если не dry_run). Уважает max/идемпотентность; без авто-apply."""  # noqa: E501
        payloads = self._collect_task_payloads(db, project_id, platform_key)
        cap = self._max_tasks()
        payloads = payloads[:cap]
        if dry_run:
            self._write_audit(
                db,
                project_id,
                audit_actions.ACTION_MEDIA_CURATION_PREVIEWED,
                {"platform_key": platform_key, "tasks": len(payloads), "dry_run": True},
            )
            return {
                "project_id": project_id,
                "dry_run": True,
                "tasks_found": len(payloads),
                "tasks_created": 0,
                "tasks": [self._payload_view(p) for p in payloads],
            }
        account_id = self._account_id(db, project_id)
        prefix = idempotency_prefix or f"cur-p{project_id}"
        created = 0
        rows: list[Any] = []
        for payload in payloads:
            key = f"{prefix}-{payload['idempotency_suffix']}"
            existing = media_curation_repository.get_by_idempotency_key(db, key)
            if existing is not None and existing.project_id == project_id:
                continue  # уже есть активная/историческая задача — не дублируем
            row = media_curation_repository.create_task(
                db,
                account_id=account_id,
                project_id=project_id,
                media_asset_id=payload.get("media_asset_id"),
                duplicate_cluster_id=payload.get("duplicate_cluster_id"),
                quality_snapshot_id=payload.get("quality_snapshot_id"),
                fingerprint_id=payload.get("fingerprint_id"),
                task_type=payload["task_type"],
                status="proposed",
                review_status="proposed",
                priority=self._default_priority(),
                title=payload["title"],
                reason=payload.get("reason"),
                suggested_action=payload.get("suggested_action"),
                suggested_tags=payload.get("suggested_tags", []),
                suggested_products=payload.get("suggested_products", []),
                suggested_technologies=payload.get("suggested_technologies", []),
                affected_media_asset_ids=payload.get("affected_media_asset_ids", []),
                source_signals=payload.get("source_signals", []),
                risk_flags=payload.get("risk_flags", []),
                confidence_score=float(payload.get("confidence_score", 0.0)),
                expires_at=datetime.now(UTC) + timedelta(seconds=self._expire_seconds()),
                idempotency_key=key,
                task_metadata=payload.get("task_metadata", {}),
            )
            created += 1
            rows.append(row)
            self._write_audit(
                db,
                project_id,
                audit_actions.ACTION_MEDIA_CURATION_TASK_CREATED,
                {"task_id": row.id, "task_type": row.task_type, "confidence": row.confidence_score},
            )
        return {
            "project_id": project_id,
            "dry_run": False,
            "tasks_found": len(payloads),
            "tasks_created": created,
            "tasks": [self._task_view(r) for r in rows[:50]],
        }

    def _collect_task_payloads(
        self, db: Session, project_id: int, platform_key: str | None
    ) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        payloads.extend(self.build_tasks_from_duplicate_clusters(db, project_id))
        payloads.extend(self.build_tasks_from_quality_snapshots(db, project_id, platform_key))
        payloads.extend(self.build_retag_tasks(db, project_id, platform_key))
        # Сортировка: сильнее уверенность — выше.
        payloads.sort(key=lambda p: p.get("confidence_score", 0.0), reverse=True)
        return payloads

    # ------------------------------------------------------------------ #
    # 3-5. Построители задач                                              #
    # ------------------------------------------------------------------ #

    def build_tasks_from_duplicate_clusters(
        self, db: Session, project_id: int
    ) -> list[dict[str, Any]]:
        """duplicate_review задачи из активных кластеров дублей."""
        out: list[dict[str, Any]] = []
        if not self._use_fingerprints():
            return out
        for cluster in media_duplicate_cluster_repository.list_active_for_project(db, project_id):
            members = list(cluster.member_media_asset_ids or [])
            canonical = cluster.canonical_media_asset_id
            out.append(
                {
                    "idempotency_suffix": f"dup-{cluster.id}",
                    "task_type": "duplicate_review",
                    "title": f"Проверить дубли ({cluster.cluster_type})",
                    "reason": "; ".join((cluster.reasons or [])[:2])
                    or "Похожие/дублирующиеся медиа.",
                    "suggested_action": "keep_canonical",
                    "duplicate_cluster_id": cluster.id,
                    "media_asset_id": canonical,
                    "affected_media_asset_ids": members,
                    "source_signals": ["duplicate_cluster"],
                    "risk_flags": [],
                    "confidence_score": round(float(cluster.similarity_score or 0.0), 3),
                    "task_metadata": {
                        "canonical_media_asset_id": canonical,
                        "cluster_type": cluster.cluster_type,
                        "member_count": len(members),
                    },
                }
            )
        return out

    def build_tasks_from_quality_snapshots(
        self, db: Session, project_id: int, platform_key: str | None = None
    ) -> list[dict[str, Any]]:
        """weak_media_review / platform_fit_issue / media_proxy_needed / heic_conversion_needed."""
        out: list[dict[str, Any]] = []
        if not self._use_quality():
            return out
        latest: dict[int, Any] = {}
        for row in media_quality_repository.list_for_project(db, project_id, limit=1000):
            latest.setdefault(row.media_asset_id, row)
        for snap in latest.values():
            issues = set(snap.issue_codes or [])
            if snap.status in ("weak",) or (
                snap.overall_score is not None and snap.overall_score < self._min_good()
            ):
                out.append(
                    self._quality_task(
                        snap,
                        "weak_media_review",
                        "Заменить слабое медиа",
                        "request_replacement",
                        "Низкая оценка качества — стоит заменить.",
                    )
                )
            if "heic_conversion_needed" in issues:
                out.append(
                    self._quality_task(
                        snap,
                        "heic_conversion_needed",
                        "Конвертировать HEIC",
                        "mark_reviewed",
                        "HEIC нужно конвертировать в JPEG перед публикацией.",
                    )
                )
            if "instagram_public_url_required" in issues or "media_proxy_not_ready" in issues:
                out.append(
                    self._quality_task(
                        snap,
                        "media_proxy_needed",
                        "Подготовить public image_url",
                        "mark_reviewed",
                        "Для Instagram нужен public image_url (media proxy).",
                    )
                )
            elif "weak_topic_match" in issues:
                out.append(
                    self._quality_task(
                        snap,
                        "platform_fit_issue",
                        "Слабая релевантность медиа",
                        "request_replacement",
                        "Медиа слабо совпадает с темой.",
                    )
                )
        return out

    def _quality_task(
        self, snap: Any, task_type: str, title: str, action: str, reason: str
    ) -> dict[str, Any]:
        return {
            "idempotency_suffix": f"{task_type}-{snap.media_asset_id}",
            "task_type": task_type,
            "title": title,
            "reason": reason,
            "suggested_action": action,
            "media_asset_id": snap.media_asset_id,
            "quality_snapshot_id": snap.id,
            "affected_media_asset_ids": [snap.media_asset_id],
            "source_signals": ["quality_snapshot"],
            "risk_flags": list(snap.issue_codes or [])[:6],
            "confidence_score": round(1.0 - (snap.overall_score or 0) / 100.0, 3),
            "task_metadata": {"overall_score": snap.overall_score, "status": snap.status},
        }

    def build_retag_tasks(
        self, db: Session, project_id: int, platform_key: str | None = None
    ) -> list[dict[str, Any]]:
        """retag_suggestion / missing_tags задачи по предложениям тегов (без AI)."""
        out: list[dict[str, Any]] = []
        min_conf = self._min_confidence()
        assets = [
            a
            for a in media_asset_repository.list_media_assets_by_project(db, project_id)
            if a.status in _USABLE_STATUSES and a.selection_visibility == "selectable"
        ]
        for asset in assets:
            suggestion = self._tag_svc().suggest_tags_for_asset(
                db, project_id, asset.id, platform_key
            )
            if not suggestion["suggested_tags"]:
                continue
            if suggestion["confidence_score"] < min_conf:
                continue
            has_tags = bool(asset.tags or {})
            task_type = "retag_suggestion" if has_tags else "missing_tags"
            title = "Подтвердить теги" if has_tags else "Добавить теги (нет тегов)"
            out.append(
                {
                    "idempotency_suffix": f"retag-{asset.id}",
                    "task_type": task_type,
                    "title": title,
                    "reason": "; ".join(suggestion.get("reasons", [])[:2])
                    or "Предложены теги из локальных сигналов.",
                    "suggested_action": "approve_tags",
                    "media_asset_id": asset.id,
                    "affected_media_asset_ids": [asset.id],
                    "suggested_tags": suggestion["suggested_tags"],
                    "suggested_products": suggestion["suggested_products"],
                    "suggested_technologies": suggestion["suggested_technologies"],
                    "source_signals": suggestion["source_signals"],
                    "risk_flags": suggestion["risk_flags"],
                    "confidence_score": suggestion["confidence_score"],
                    "task_metadata": {"has_existing_tags": has_tags},
                }
            )
        return out

    # ------------------------------------------------------------------ #
    # 6-9. Применение / отклонение / восстановление                      #
    # ------------------------------------------------------------------ #

    def apply_task(
        self, db: Session, task_id: int, action: str, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """Применить задачу (approve_tags/mark_duplicate/hide/restore/ignore_cluster/reviewed)."""
        task = media_curation_repository.get_task_by_id(db, task_id)
        if task is None:
            raise MediaCurationError("Задача не найдена")
        if task.status in ("applied", "rejected", "ignored"):
            return {**self._task_view(task), "outcome": "already_final"}
        # Гейт согласования (v0.4.9): изменяющие медиа действия — только после approved.
        if (
            action in MEDIA_CURATION_APPROVAL_REQUIRED_ACTIONS
            and self._require_approval()
            and task.review_status != "approved"
        ):
            return {
                **self._task_view(task),
                "outcome": "requires_approval",
                "blocked": True,
            }
        project_id = task.project_id

        if action == "approve_tags":
            self._apply_tags(db, task, current_user_id)
        elif action == "mark_duplicate":
            self._hide_duplicates(db, task, current_user_id)
        elif action == "hide_from_selection":
            visibility = "hidden_weak" if task.task_type == "weak_media_review" else "hidden_manual"
            self._hide_media(
                db, project_id, task.media_asset_id, visibility, task.id, current_user_id
            )
        elif action == "restore_to_selection":
            self.restore_media(db, project_id, task.media_asset_id, current_user_id)
        elif action == "ignore_cluster":
            if task.duplicate_cluster_id is not None:
                cluster = media_duplicate_cluster_repository.get_by_id(
                    db, task.duplicate_cluster_id
                )
                if cluster is not None and cluster.project_id == project_id:
                    media_duplicate_cluster_repository.mark_ignored(db, cluster, current_user_id)
            media_curation_repository.mark_ignored(db, task, current_user_id)
            self._write_audit(
                db,
                project_id,
                audit_actions.ACTION_MEDIA_CURATION_TASK_IGNORED,
                {"task_id": task.id, "action": action},
            )
            return {**self._task_view(task), "outcome": "ignored"}
        elif action == "mark_reviewed":
            pass
        else:
            raise MediaCurationError(f"Действие не поддерживается: {action}")

        media_curation_repository.mark_applied(db, task, current_user_id)
        self._write_audit(
            db,
            project_id,
            audit_actions.ACTION_MEDIA_CURATION_TASK_APPLIED,
            {"task_id": task.id, "action": action, "task_type": task.task_type},
        )
        return {**self._task_view(task), "outcome": "applied"}

    def reject_task(
        self,
        db: Session,
        task_id: int,
        reason: str | None = None,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Отклонить задачу (без изменений медиа)."""
        task = media_curation_repository.get_task_by_id(db, task_id)
        if task is None:
            raise MediaCurationError("Задача не найдена")
        media_curation_repository.mark_rejected(db, task, reason, current_user_id)
        self._write_audit(
            db,
            task.project_id,
            audit_actions.ACTION_MEDIA_CURATION_TASK_REJECTED,
            {"task_id": task.id},
        )
        return {**self._task_view(task), "outcome": "rejected"}

    def ignore_task(
        self, db: Session, task_id: int, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """Проигнорировать задачу."""
        task = media_curation_repository.get_task_by_id(db, task_id)
        if task is None:
            raise MediaCurationError("Задача не найдена")
        media_curation_repository.mark_ignored(db, task, current_user_id)
        self._write_audit(
            db,
            task.project_id,
            audit_actions.ACTION_MEDIA_CURATION_TASK_IGNORED,
            {"task_id": task.id},
        )
        return {**self._task_view(task), "outcome": "ignored"}

    def restore_media(
        self,
        db: Session,
        project_id: int,
        media_asset_id: int | None,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Вернуть медиа в подбор (selectable). Файл не трогаем."""
        if media_asset_id is None:
            raise MediaCurationError("Не указан media_asset_id")
        asset = media_asset_repository.get_media_asset_by_id(db, media_asset_id)
        if asset is None or asset.project_id != project_id:
            raise MediaCurationError("Медиа не принадлежит проекту")
        media_curation_repository.restore_media_visibility(db, media_asset_id)
        self._write_audit(
            db,
            project_id,
            audit_actions.ACTION_MEDIA_CURATION_MEDIA_RESTORED,
            {"media_asset_id": media_asset_id},
        )
        return {"media_asset_id": media_asset_id, "selection_visibility": "selectable"}

    # ------------------------------------------------------------------ #
    # 10. Дашборд                                                         #
    # ------------------------------------------------------------------ #

    def build_curation_dashboard(
        self, db: Session, project_id: int, platform_key: str | None = None
    ) -> dict[str, Any]:
        """Сводка курирования медиатеки проекта для UI."""
        tasks = media_curation_repository.list_tasks_for_project(db, project_id, limit=1000)
        active = [t for t in tasks if t.status in ("proposed", "accepted")]
        by_type: dict[str, int] = {}
        issues: dict[str, int] = {}
        for t in active:
            by_type[t.task_type] = by_type.get(t.task_type, 0) + 1
            for flag in t.risk_flags or []:
                issues[flag] = issues.get(flag, 0) + 1
        applied = [t for t in tasks if t.status == "applied"]
        hidden = media_curation_repository.count_hidden_media(db, project_id)
        selectable = len(media_curation_repository.list_selectable_media_assets(db, project_id))
        return {
            "project_id": project_id,
            "platform_key": platform_key,
            "active_tasks": len(active),
            "duplicate_tasks": by_type.get("duplicate_review", 0),
            "retag_tasks": by_type.get("retag_suggestion", 0) + by_type.get("missing_tags", 0),
            "weak_media_tasks": by_type.get("weak_media_review", 0),
            "hidden_media_count": hidden,
            "selectable_media_count": selectable,
            "common_issues": sorted(issues.items(), key=lambda kv: kv[1], reverse=True)[:8],
            "recommended_actions": self._recommended_actions(by_type),
            "recent_applied": [self._task_view(t) for t in applied[:10]],
            "worker_enabled": self._worker_enabled(),
        }

    # ------------------------------------------------------------------ #
    # Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    def _apply_tags(self, db: Session, task: Any, user_id: int | None) -> None:
        if task.media_asset_id is None:
            return
        asset = media_asset_repository.get_media_asset_by_id(db, task.media_asset_id)
        if asset is None or asset.project_id != task.project_id:
            raise MediaCurationError("Медиа не принадлежит проекту")
        tags = {k: list(v or []) for k, v in dict(asset.tags or {}).items()}

        def _merge(group: str, values: list[str]) -> None:
            cur = tags.get(group, [])
            lower = {str(x).strip().lower() for x in cur}
            for v in values:
                if v and v.strip().lower() not in lower:
                    cur.append(v)
                    lower.add(v.strip().lower())
            tags[group] = cur

        _merge("products", list(task.suggested_products or []))
        _merge("technologies", list(task.suggested_technologies or []))
        details = [
            t
            for t in (task.suggested_tags or [])
            if t not in (task.suggested_products or [])
            and t not in (task.suggested_technologies or [])
        ]
        _merge("details", details)
        asset.tags = tags
        asset.curation_status = "reviewed"
        db.commit()
        self._write_audit(
            db,
            task.project_id,
            audit_actions.ACTION_MEDIA_CURATION_TAGS_APPLIED,
            {
                "media_asset_id": asset.id,
                "task_id": task.id,
                "suggested_tags": list(task.suggested_tags or [])[:12],
            },
        )

    def _hide_duplicates(self, db: Session, task: Any, user_id: int | None) -> None:
        canonical = (task.task_metadata or {}).get("canonical_media_asset_id")
        for mid in task.affected_media_asset_ids or []:
            if mid == canonical:
                continue
            self._hide_media(db, task.project_id, mid, "hidden_duplicate", task.id, user_id)

    def _hide_media(
        self,
        db: Session,
        project_id: int,
        media_asset_id: int | None,
        visibility: str,
        task_id: int,
        user_id: int | None,
    ) -> None:
        if media_asset_id is None:
            return
        asset = media_asset_repository.get_media_asset_by_id(db, media_asset_id)
        if asset is None or asset.project_id != project_id:
            return
        media_curation_repository.set_media_visibility(
            db, media_asset_id, visibility, notes={"hidden_by_task": task_id, "reason": visibility}
        )
        self._write_audit(
            db,
            project_id,
            audit_actions.ACTION_MEDIA_CURATION_MEDIA_HIDDEN,
            {"media_asset_id": media_asset_id, "visibility": visibility, "task_id": task_id},
        )

    @staticmethod
    def _recommended_actions(by_type: dict[str, int]) -> list[str]:
        actions: list[str] = []
        if by_type.get("duplicate_review"):
            actions.append("Проверьте дубли и оставьте canonical.")
        if by_type.get("retag_suggestion") or by_type.get("missing_tags"):
            actions.append("Подтвердите предложенные теги.")
        if by_type.get("weak_media_review"):
            actions.append("Замените слабые медиа.")
        if by_type.get("media_proxy_needed"):
            actions.append("Подготовьте public image_url для Instagram.")
        return actions

    def _payload_view(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Безопасный вид ещё не сохранённой задачи (без путей/секретов).
        return {
            "task_type": payload["task_type"],
            "title": payload["title"],
            "reason": payload.get("reason"),
            "suggested_action": payload.get("suggested_action"),
            "media_asset_id": payload.get("media_asset_id"),
            "duplicate_cluster_id": payload.get("duplicate_cluster_id"),
            "quality_snapshot_id": payload.get("quality_snapshot_id"),
            "affected_media_asset_ids": payload.get("affected_media_asset_ids", []),
            "suggested_tags": payload.get("suggested_tags", []),
            "suggested_products": payload.get("suggested_products", []),
            "suggested_technologies": payload.get("suggested_technologies", []),
            "source_signals": payload.get("source_signals", []),
            "risk_flags": payload.get("risk_flags", []),
            "confidence_score": payload.get("confidence_score", 0.0),
        }

    def _task_view(self, task: Any) -> dict[str, Any]:
        # ВНИМАНИЕ: только безопасные поля. Никаких путей к файлам/секретов.
        return {
            "id": task.id,
            "project_id": task.project_id,
            "media_asset_id": task.media_asset_id,
            "duplicate_cluster_id": task.duplicate_cluster_id,
            "quality_snapshot_id": task.quality_snapshot_id,
            "task_type": task.task_type,
            "status": task.status,
            "title": task.title,
            "reason": task.reason,
            "suggested_action": task.suggested_action,
            "suggested_tags": list(task.suggested_tags or []),
            "suggested_products": list(task.suggested_products or []),
            "suggested_technologies": list(task.suggested_technologies or []),
            "affected_media_asset_ids": list(task.affected_media_asset_ids or []),
            "source_signals": list(task.source_signals or []),
            "risk_flags": list(task.risk_flags or []),
            "confidence_score": round(task.confidence_score, 3),
            "created_at": task.created_at.isoformat() if task.created_at else None,
            # Collaborative review (v0.4.9): безопасные поля согласования.
            "review_status": getattr(task, "review_status", "proposed"),
            "priority": getattr(task, "priority", "normal"),
            "assignee_user_id": getattr(task, "assignee_user_id", None),
            "reviewer_user_id": getattr(task, "reviewer_user_id", None),
            "due_at": task.due_at.isoformat() if getattr(task, "due_at", None) else None,
            "approved_at": (
                task.approved_at.isoformat() if getattr(task, "approved_at", None) else None
            ),
        }

    @staticmethod
    def _account_id(db: Session, project_id: int) -> int | None:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise MediaCurationError(f"Проект id={project_id} не найден")
        return project.account_id

    # --- Настройки / зависимости ---

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _worker_enabled(self) -> bool:
        return bool(self._resolve_settings().media_curation_worker_enabled_effective)

    def _min_confidence(self) -> float:
        return float(self._resolve_settings().media_curation_min_confidence_safe)

    def _max_tasks(self) -> int:
        return int(self._resolve_settings().media_curation_max_tasks_per_run_safe)

    def _expire_seconds(self) -> int:
        return int(self._resolve_settings().media_curation_task_expire_seconds)

    def _min_good(self) -> int:
        return int(getattr(self._resolve_settings(), "media_quality_min_good_score_safe", 70))

    def _require_approval(self) -> bool:
        """Требуется ли approved перед применением изменений (v0.4.9)."""
        return bool(
            getattr(
                self._resolve_settings(),
                "media_curation_review_require_approval_effective",
                True,
            )
        )

    def _default_priority(self) -> str:
        """Приоритет новой задачи по умолчанию (v0.4.9)."""
        return str(
            getattr(
                self._resolve_settings(), "media_curation_review_default_priority_safe", "normal"
            )
        )

    def _use_fingerprints(self) -> bool:
        return bool(getattr(self._resolve_settings(), "media_curation_use_fingerprints", True))

    def _use_quality(self) -> bool:
        return bool(getattr(self._resolve_settings(), "media_curation_use_quality", True))

    def _tag_svc(self) -> MediaTagSuggestionService:
        if self._tags is None:
            from app.services.media_tag_suggestion_service import MediaTagSuggestionService

            self._tags = MediaTagSuggestionService(settings=self._settings)
        return self._tags

    def _audit_svc(self) -> AuditLogService:
        if self._audit is None:
            from app.services.audit_log_service import AuditLogService

            self._audit = AuditLogService()
        return self._audit

    def _write_audit(
        self, db: Session, project_id: int, action: str, metadata: dict[str, Any]
    ) -> None:
        project = project_repository.get_project_by_id(db, project_id)
        account_id = project.account_id if project is not None else None
        self._audit_svc().record(
            db,
            action,
            account_id=account_id,
            project_id=project_id,
            entity_type="media_curation_task",
            metadata=metadata,
        )


def get_media_curation_service() -> MediaCurationService:
    """DI-фабрика сервиса курирования медиатеки."""
    return MediaCurationService()
