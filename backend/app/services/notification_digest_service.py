"""Сервис дайджестов уведомлений — v0.5.1.

Собирает недавние уведомления пользователя в daily/weekly дайджест: preview (без записи),
генерация (write), отправка (через delivery-канал digest) и планировщик. РЕАЛЬНОЙ отправки
нет: дайджест генерируется/логируется, но наружу ничего не идёт; выключено по умолчанию.

БЕЗОПАСНОСТЬ:
- subject/body санитизируются (без секретов и внутренних путей); только id уведомлений;
- дайджест НЕ роняет основной workflow.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.repositories import (
    notification_delivery_repository as delivery_repo,
)
from app.repositories import (
    notification_repository,
    project_repository,
    user_repository,
)
from app.services import audit_log_service as audit_actions
from app.services.notification_service import sanitize_text

if TYPE_CHECKING:
    from app.config import Settings
    from app.services.audit_log_service import AuditLogService
    from app.services.notification_delivery_service import NotificationDeliveryService

logger = get_logger(__name__)

_FREQUENCY_DAYS = {"daily": 1, "weekly": 7}


class NotificationDigestError(Exception):
    """Ошибка дайджеста (нет доступа/сущности) — API → 400/403/404."""


class NotificationDigestService:
    """Дайджесты уведомлений: preview/generate/send/scheduler (без реальной отправки)."""

    def __init__(
        self,
        delivery_service: NotificationDeliveryService | None = None,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._delivery = delivery_service
        self._audit = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # 1. Preview (без записи)                                             #
    # ------------------------------------------------------------------ #

    def preview_digest(
        self,
        db: Session,
        user_id: int,
        frequency: str = "daily",
        project_id: int | None = None,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Предпросмотр дайджеста: subject/body по недавним уведомлениям (без записи)."""
        self._check_access(user_id, current_user_id)
        frequency = self._valid_frequency(frequency)
        start, end = self._period(frequency, period_start, period_end)
        notifications = self._collect(db, user_id, start, end, project_id)
        subject = self._subject(frequency, len(notifications))
        body = self.build_digest_body(notifications)
        self._write_audit(
            db,
            audit_actions.ACTION_NOTIFICATION_DIGEST_PREVIEWED,
            user_id,
            project_id,
            {"frequency": frequency, "notification_count": len(notifications)},
        )
        return {
            "user_id": user_id,
            "frequency": frequency,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "notification_count": len(notifications),
            "notification_ids": [n.id for n in notifications],
            "subject": subject,
            "body_preview": body,
            "digest_enabled": self._digest_enabled(),
            "external_delivery_enabled": self._external_enabled(),
            "dry_run_default": True,
        }

    # ------------------------------------------------------------------ #
    # 2. Генерация (write)                                                #
    # ------------------------------------------------------------------ #

    def generate_digest(
        self,
        db: Session,
        user_id: int,
        frequency: str = "daily",
        project_id: int | None = None,
        dry_run: bool = True,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Сгенерировать дайджест. Dry-run — без записи; write — создаёт запись (без отправки)."""
        self._check_access(user_id, current_user_id)
        frequency = self._valid_frequency(frequency)
        start, end = self._period(frequency, None, None)
        notifications = self._collect(db, user_id, start, end, project_id)
        subject = self._subject(frequency, len(notifications))
        body = self.build_digest_body(notifications)
        if dry_run:
            return {
                "dry_run": True,
                "user_id": user_id,
                "frequency": frequency,
                "notification_count": len(notifications),
                "subject": subject,
                "body_preview": body,
                "digest_id": None,
            }
        account_id = self._account_id(db, project_id)
        digest = delivery_repo.create_digest(
            db,
            account_id=account_id,
            project_id=project_id,
            user_id=user_id,
            frequency=frequency,
            status="draft",
            period_start=start,
            period_end=end,
            notification_ids=[n.id for n in notifications],
            subject=subject,
            body_preview=body,
        )
        delivery_repo.mark_digest_generated(db, digest)
        self._write_audit(
            db,
            audit_actions.ACTION_NOTIFICATION_DIGEST_GENERATED,
            user_id,
            project_id,
            {"digest_id": digest.id, "notification_count": len(notifications)},
        )
        return {
            "dry_run": False,
            "user_id": user_id,
            "frequency": frequency,
            "notification_count": len(notifications),
            "subject": subject,
            "digest_id": digest.id,
        }

    # ------------------------------------------------------------------ #
    # 3. Отправка дайджеста                                               #
    # ------------------------------------------------------------------ #

    def send_digest(
        self, db: Session, digest_id: int, dry_run: bool = True, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """«Отправить» дайджест через delivery-канал digest (без внешней доставки по умолчанию)."""
        digest = delivery_repo.get_digest_by_id(db, digest_id)
        if digest is None:
            raise NotificationDigestError("Дайджест не найден")
        self._check_access(digest.user_id, current_user_id)
        if digest.status == "sent":
            return {"digest_id": digest.id, "outcome": "already_sent"}
        # Создаём delivery-задачу канала digest на «якорное» уведомление (если есть) или без него.
        anchor_id = digest.notification_ids[0] if digest.notification_ids else None
        outcome = "skipped"
        delivery_log_id: int | None = None
        if anchor_id is not None:
            try:
                result = self._delivery_service().send_notification(
                    db, anchor_id, channels=["digest"], dry_run=dry_run
                )
                results = result.get("results") or []
                if results:
                    delivery_log_id = results[0].get("id")
                    outcome = results[0].get("outcome", "skipped")
            except Exception:  # noqa: BLE001 — дайджест не роняет workflow
                logger.warning("digest delivery failed digest_id=%s", digest_id)
        if dry_run:
            self._write_audit(
                db,
                audit_actions.ACTION_NOTIFICATION_DIGEST_SENT,
                digest.user_id,
                digest.project_id,
                {"digest_id": digest.id, "dry_run": True, "outcome": outcome},
            )
            return {"digest_id": digest.id, "outcome": outcome, "dry_run": True}
        delivery_repo.mark_digest_sent(db, digest, delivery_log_id)
        self._write_audit(
            db,
            audit_actions.ACTION_NOTIFICATION_DIGEST_SENT,
            digest.user_id,
            digest.project_id,
            {"digest_id": digest.id, "delivery_log_id": delivery_log_id, "outcome": outcome},
        )
        return {"digest_id": digest.id, "outcome": "sent", "delivery_log_id": delivery_log_id}

    # ------------------------------------------------------------------ #
    # 4. Планировщик                                                      #
    # ------------------------------------------------------------------ #

    def run_digest_scheduler(
        self, db: Session, frequency: str = "daily", dry_run: bool = True, limit: int = 100
    ) -> dict[str, Any]:
        """Найти пользователей с включённым дайджестом и сгенерировать/отправить (dry-run)."""
        frequency = self._valid_frequency(frequency)
        if not self._digest_enabled():
            self._write_audit(
                db,
                audit_actions.ACTION_NOTIFICATION_DIGEST_SCHEDULER_PREVIEWED,
                None,
                None,
                {"frequency": frequency, "users": 0, "enabled": False},
            )
            return {
                "dry_run": dry_run,
                "frequency": frequency,
                "users": 0,
                "generated": 0,
                "enabled": False,
            }
        user_ids = delivery_repo.list_digest_user_ids(db, frequency, limit=limit)
        generated = 0
        for uid in user_ids:
            result = self.generate_digest(db, uid, frequency=frequency, dry_run=dry_run)
            if not dry_run and result.get("digest_id"):
                self.send_digest(db, result["digest_id"], dry_run=dry_run)
                generated += 1
            elif dry_run:
                generated += 1
        self._write_audit(
            db,
            audit_actions.ACTION_NOTIFICATION_DIGEST_SCHEDULER_PREVIEWED,
            None,
            None,
            {"frequency": frequency, "users": len(user_ids), "generated": generated},
        )
        return {
            "dry_run": dry_run,
            "frequency": frequency,
            "users": len(user_ids),
            "generated": generated,
            "enabled": True,
        }

    # ------------------------------------------------------------------ #
    # 5. Тело дайджеста                                                   #
    # ------------------------------------------------------------------ #

    def build_digest_body(self, notifications: list[Any]) -> str:
        """Собрать безопасный текст дайджеста, сгруппированный по проекту/типу/приоритету."""
        if not notifications:
            return "Новых уведомлений нет."
        by_project: dict[str, list[Any]] = {}
        for n in notifications:
            key = f"проект #{n.project_id}" if n.project_id else "без проекта"
            by_project.setdefault(key, []).append(n)
        lines: list[str] = [f"Дайджест: {len(notifications)} уведомлений."]
        for project_key, items in by_project.items():
            lines.append(f"\n{project_key}:")
            for n in items[:50]:
                title = sanitize_text(n.title, 120)
                url = f" — {n.action_url}" if n.action_url else ""
                lines.append(f"  • [{n.priority}] {n.notification_type}: {title}{url}")
        return sanitize_text("\n".join(lines), 4000)

    # ------------------------------------------------------------------ #
    # Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    def _collect(
        self, db: Session, user_id: int, start: datetime, end: datetime, project_id: int | None
    ) -> list[Any]:
        rows = notification_repository.list_for_user(
            db, user_id, project_id=project_id, limit=self._max_notifications() * 3
        )
        picked: list[Any] = []
        for n in rows:
            created = n.created_at
            if created is None:
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            if start <= created <= end:
                picked.append(n)
            if len(picked) >= self._max_notifications():
                break
        return picked

    def _period(
        self, frequency: str, period_start: datetime | None, period_end: datetime | None
    ) -> tuple[datetime, datetime]:
        end = period_end or datetime.now(UTC)
        start = period_start or (end - timedelta(days=_FREQUENCY_DAYS.get(frequency, 1)))
        return start, end

    @staticmethod
    def _subject(frequency: str, count: int) -> str:
        label = "ежедневный" if frequency == "daily" else "еженедельный"
        return f"Botfleet: {label} дайджест — {count} уведомлений"

    def _check_access(self, user_id: int, current_user_id: int | None) -> None:
        if current_user_id is not None and current_user_id != user_id:
            raise NotificationDigestError("Нет доступа к дайджесту пользователя")

    @staticmethod
    def _valid_frequency(frequency: str) -> str:
        value = str(frequency or "daily").strip().lower()
        return value if value in ("daily", "weekly") else "daily"

    def _account_id(self, db: Session, project_id: int | None) -> int | None:
        if project_id is None:
            return None
        project = project_repository.get_project_by_id(db, project_id)
        return project.account_id if project is not None else None

    def _write_audit(
        self,
        db: Session,
        action: str,
        user_id: int | None,
        project_id: int | None,
        extra: dict[str, Any],
    ) -> None:
        account_id = None
        if user_id is not None:
            user = user_repository.get_user_by_id(db, user_id)
            account_id = None if user is None else self._account_id(db, project_id)
        self._audit_svc().record(
            db,
            action,
            account_id=account_id,
            project_id=project_id,
            user_id=user_id,
            entity_type="notification_digest",
            metadata=extra,
        )

    # --- settings/deps ---

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _digest_enabled(self) -> bool:
        return bool(self._resolve_settings().notification_digest_enabled_effective)

    def _external_enabled(self) -> bool:
        return bool(self._resolve_settings().notification_external_delivery_enabled_effective)

    def _max_notifications(self) -> int:
        return int(self._resolve_settings().notification_digest_max_notifications_safe)

    def _delivery_service(self) -> NotificationDeliveryService:
        if self._delivery is None:
            from app.services.notification_delivery_service import NotificationDeliveryService

            self._delivery = NotificationDeliveryService(settings=self._settings)
        return self._delivery

    def _audit_svc(self) -> AuditLogService:
        if self._audit is None:
            from app.services.audit_log_service import AuditLogService

            self._audit = AuditLogService()
        return self._audit


def get_notification_digest_service() -> NotificationDigestService:
    """DI-фабрика сервиса дайджестов."""
    return NotificationDigestService()
