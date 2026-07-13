"""Сервис Telegram-first live rollout — v0.6.0.

Первый безопасный реальный live-канал автопилота. Сервис проверяет готовность, показывает дашборд,
делает preview/dry-run и (только когда явно всё включено) пытается реальную публикацию в Telegram
через существующий ``PostPublicationService``. Каждая попытка фиксируется в ``LivePublishAttempt``.

БЕЗОПАСНОСТЬ (инварианты):
- реальная отправка возможна ТОЛЬКО если ВСЕ условия true: глобальный
  ``TELEGRAM_LIVE_PUBLISHING_ENABLED`` + per-project live + per-platform live + full_auto live +
  readiness_ready + ``TELEGRAM_LIVE_ROLLOUT_ALLOW_REAL_SEND`` + подтверждение
  ``ENABLE_TELEGRAM_LIVE``;
- сервис НИКОГДА не включает и не меняет глобальные live-флаги;
- preview/dry-run/blocked попытки НЕ списывают деньги и НЕ ходят в сеть;
- в журнал не попадают токены/сырые payload/внутренние пути;
- ``publish_due`` не вызывается.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import (
    live_publish_attempt_repository as attempt_repo,
)
from app.repositories import (
    post_publication_repository,
    post_repository,
    project_repository,
)
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

_PLATFORM = "telegram"


class TelegramLiveRolloutError(Exception):
    """Ошибка Telegram live rollout (нет проекта/доступа/данных) — API → 400/404."""


class TelegramLiveRolloutService:
    """Telegram-first live rollout: дашборд, preview, dry-run, run-once (под всеми гейтами)."""

    def __init__(
        self,
        readiness_service: Any | None = None,
        publication_service: Any | None = None,
        billing_service: Any | None = None,
        notification_service: Any | None = None,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._readiness = readiness_service
        self._publication = publication_service
        self._billing = billing_service
        self._notification = notification_service
        self._audit = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Эффективный статус Telegram live                                    #
    # ------------------------------------------------------------------ #

    def build_effective_telegram_live_status(self, db: Session, project_id: int) -> dict[str, Any]:
        """Итоговый статус Telegram live (readiness gate + rollout allow_real_send)."""
        settings = self._resolve_settings()
        gate = self._readiness_service().build_effective_live_gate(db, project_id, _PLATFORM)
        allow_real_send = settings.telegram_live_rollout_allow_real_send_effective
        can_attempt_live = bool(gate.get("can_publish_live"))
        can_send_real = bool(can_attempt_live and allow_real_send)
        blocked_reasons = list(gate.get("blocked_reasons", []))
        if not allow_real_send:
            blocked_reasons.append("rollout_real_send_disabled")
        return {
            "global_live_enabled": bool(gate.get("global_live_enabled")),
            "rollout_allow_real_send": allow_real_send,
            "project_live_enabled": bool(gate.get("project_live_enabled")),
            "platform_live_enabled": bool(gate.get("platform_live_enabled")),
            "full_auto_live_enabled": bool(gate.get("full_auto_live_enabled")),
            "readiness_ready": bool(gate.get("readiness_ready")),
            "can_attempt_live": can_attempt_live,
            "can_send_real": can_send_real,
            "blocked_reasons": blocked_reasons,
        }

    # ------------------------------------------------------------------ #
    # Dashboard                                                          #
    # ------------------------------------------------------------------ #

    def build_dashboard(self, db: Session, project_id: int) -> dict[str, Any]:
        """Клиентский дашборд Telegram live rollout."""
        project = self._require_project(db, project_id)
        settings = self._resolve_settings()
        status = self.build_effective_telegram_live_status(db, project_id)
        tg_platform = self._telegram_platform_status(db, project_id)
        summary = attempt_repo.build_project_attempt_summary(db, project_id)
        recent = [
            attempt_repo.public_attempt_view(a)
            for a in attempt_repo.list_attempts_for_project(db, project_id, limit=10)
        ]
        blockers = self._status_blockers(status, tg_platform)
        rollout_status = self._rollout_status(status, blockers)
        self._write_audit(
            db,
            audit_actions.ACTION_TELEGRAM_LIVE_ROLLOUT_DASHBOARD_VIEWED,
            project.account_id,
            project_id,
            {"status": rollout_status},
        )
        return {
            "project_id": project_id,
            "status": rollout_status,
            "readiness": {
                "ready": status["readiness_ready"],
                "can_attempt_live": status["can_attempt_live"],
                "can_send_real": status["can_send_real"],
            },
            "telegram_platform_status": tg_platform,
            "global_live_flag_status": status["global_live_enabled"],
            "project_live_status": status["project_live_enabled"],
            "platform_live_status": status["platform_live_enabled"],
            "full_auto_live_status": status["full_auto_live_enabled"],
            "rollout_allow_real_send": status["rollout_allow_real_send"],
            "last_attempt": summary["last_attempt"],
            "recent_attempts": recent,
            "attempt_summary": summary,
            "blockers": blockers,
            "warnings": [],
            "confirmation": {
                "text": settings.telegram_live_rollout_confirmation_text_safe,
                "required": settings.telegram_live_rollout_require_confirmation_effective,
            },
            "next_best_action": self._next_action(status, tg_platform),
            "client_summary": self._client_summary(rollout_status, status),
            "note": (
                "Реальная отправка сработает только если production-условия публикации включены "
                "администратором и разрешена реальная отправка rollout."
            ),
        }

    # ------------------------------------------------------------------ #
    # Preview                                                            #
    # ------------------------------------------------------------------ #

    def preview_post(
        self,
        db: Session,
        project_id: int,
        post_id: int | None = None,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Безопасный предпросмотр Telegram-публикации (без записи и без сети)."""
        project = self._require_project(db, project_id)
        status = self.build_effective_telegram_live_status(db, project_id)
        post = self._resolve_post(db, project_id, post_id, None)
        payload_preview: dict[str, Any] = {"available": False}
        estimated_units = 0
        if post is not None:
            payload_preview = self._safe_payload_preview(db, post.id)
            estimated_units = self._autopost_cost()
        self._write_audit(
            db,
            audit_actions.ACTION_TELEGRAM_LIVE_ROLLOUT_PREVIEWED,
            project.account_id,
            project_id,
            {"post_id": post.id if post else None},
        )
        return {
            "project_id": project_id,
            "post_id": post.id if post else None,
            "effective_status": status,
            "payload_preview": payload_preview,
            "blockers": [{"type": r} for r in status["blocked_reasons"]],
            "estimated_units": estimated_units,
            "writes": False,
            "live_calls": False,
            "note": "Предпросмотр. Ничего не отправлено, деньги не списаны.",
        }

    def create_attempt_preview(
        self,
        db: Session,
        project_id: int,
        post_id: int | None = None,
        publication_id: int | None = None,
        trigger: str = "manual_preview",
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Создать запись-preview LivePublishAttempt (без сети, без списания)."""
        project = self._require_project(db, project_id)
        status = self.build_effective_telegram_live_status(db, project_id)
        post = self._resolve_post(db, project_id, post_id, publication_id)
        attempt = attempt_repo.create_attempt(
            db,
            account_id=project.account_id,
            project_id=project_id,
            platform_key=_PLATFORM,
            post_id=post.id if post else None,
            publication_id=publication_id,
            trigger=trigger,
            mode="dry_run",
            status="preview",
            **self._gate_fields(status),
            request_summary=self._safe_payload_preview(db, post.id) if post else {},
            blockers=[{"type": r} for r in status["blocked_reasons"]],
            confirmed_by_user_id=current_user_id,
        )
        return attempt_repo.public_attempt_view(attempt)

    # ------------------------------------------------------------------ #
    # Run-once (dry) / publish-once                                      #
    # ------------------------------------------------------------------ #

    def run_once_dry(
        self,
        db: Session,
        project_id: int,
        post_id: int | None = None,
        publication_id: int | None = None,
        current_user_id: int | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Тестовый прогон БЕЗ реальной отправки: проверяет гейты и пишет attempt. Без списания."""
        project = self._require_project(db, project_id)
        status = self.build_effective_telegram_live_status(db, project_id)
        post = self._resolve_post(db, project_id, post_id, publication_id)
        blockers = [{"type": r} for r in status["blocked_reasons"]]
        if post is None:
            blockers.append({"type": "post_missing"})
        # Dry-run: реальной отправки нет никогда. Если все гейты прошли — статус skipped,
        # иначе blocked (для наглядности, что мешает).
        attempt_status = "skipped" if (status["can_attempt_live"] and post) else "blocked"
        attempt = attempt_repo.create_attempt(
            db,
            account_id=project.account_id,
            project_id=project_id,
            platform_key=_PLATFORM,
            post_id=post.id if post else None,
            publication_id=publication_id,
            trigger="manual_test",
            mode="dry_run",
            status=attempt_status,
            **self._gate_fields(status),
            request_summary=self._safe_payload_preview(db, post.id) if post else {},
            blockers=blockers,
            idempotency_key=idempotency_key,
            confirmed_by_user_id=current_user_id,
        )
        self._write_audit(
            db,
            audit_actions.ACTION_TELEGRAM_LIVE_ROLLOUT_RUN_DRY,
            project.account_id,
            project_id,
            {"attempt_id": attempt.id, "status": attempt_status},
        )
        return {
            **attempt_repo.public_attempt_view(attempt),
            "live_calls": False,
            "units_charged": 0,
            "note": "Тестовый прогон. Реальной отправки нет, деньги не списаны.",
        }

    def publish_once_if_allowed(
        self,
        db: Session,
        project_id: int,
        post_id: int | None = None,
        publication_id: int | None = None,
        confirmation: str | None = None,
        current_user_id: int | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Однократная реальная публикация в Telegram — ТОЛЬКО если все гейты и флаги true.

        По умолчанию (allow_real_send=false, глобальный флаг off) — всегда blocked, без сети и
        без списания. Реальная отправка делегируется в ``PostPublicationService.publish_post``.
        """
        project = self._require_project(db, project_id)
        settings = self._resolve_settings()
        status = self.build_effective_telegram_live_status(db, project_id)
        post = self._resolve_post(db, project_id, post_id, publication_id)

        blockers = self._publish_blockers(db, project_id, status, post, confirmation, settings)
        if blockers:
            attempt = attempt_repo.create_attempt(
                db,
                account_id=project.account_id,
                project_id=project_id,
                platform_key=_PLATFORM,
                post_id=post.id if post else None,
                publication_id=publication_id,
                trigger="manual_run_once",
                mode="live_blocked",
                status="blocked",
                **self._gate_fields(status),
                request_summary=self._safe_payload_preview(db, post.id) if post else {},
                blockers=blockers,
                idempotency_key=idempotency_key,
                confirmed_by_user_id=current_user_id,
            )
            self._write_audit(
                db,
                audit_actions.ACTION_TELEGRAM_LIVE_ROLLOUT_LIVE_BLOCKED,
                project.account_id,
                project_id,
                {"attempt_id": attempt.id, "reasons": [b["type"] for b in blockers]},
            )
            self._notify(db, project, attempt, published=False)
            return {
                **attempt_repo.public_attempt_view(attempt),
                "live_calls": False,
                "units_charged": 0,
                "note": "Публикация заблокирована условиями безопасности. Ничего не отправлено.",
            }

        # --- Все гейты пройдены и реальная отправка разрешена ---
        assert post is not None  # noqa: S101 — гарантировано отсутствием post_missing выше
        attempt = attempt_repo.create_attempt(
            db,
            account_id=project.account_id,
            project_id=project_id,
            platform_key=_PLATFORM,
            post_id=post.id,
            publication_id=publication_id,
            trigger="manual_run_once",
            mode="live",
            status="attempted",
            **self._gate_fields(status),
            live_attempted=True,
            request_summary=self._safe_payload_preview(db, post.id),
            idempotency_key=idempotency_key,
            confirmed_by_user_id=current_user_id,
        )
        self._write_audit(
            db,
            audit_actions.ACTION_TELEGRAM_LIVE_ROLLOUT_LIVE_ATTEMPTED,
            project.account_id,
            project_id,
            {"attempt_id": attempt.id, "post_id": post.id},
        )
        return self._do_real_publish(db, project, attempt, post, current_user_id)

    def _do_real_publish(
        self, db: Session, project: Any, attempt: Any, post: Any, current_user_id: int | None
    ) -> dict[str, Any]:
        from app.schemas.post_publication import PostPublishRequest

        try:
            result = self._publication_service().publish_post(
                db, post.id, PostPublishRequest(platforms=[_PLATFORM])
            )
            published = int(getattr(result, "published_count", 0)) > 0
            failed = int(getattr(result, "failed_count", 0))
            response_summary = {
                "published_count": int(getattr(result, "published_count", 0)),
                "failed_count": failed,
                "skipped_count": int(getattr(result, "skipped_count", 0)),
            }
        except Exception as exc:  # noqa: BLE001 — сбой публикации не должен ронять сервис
            logger.warning("telegram live publish failed for project_id=%s", project.id)
            attempt_repo.mark_failed(db, attempt, error_message=type(exc).__name__)
            self._write_audit(
                db,
                audit_actions.ACTION_TELEGRAM_LIVE_ROLLOUT_FAILED,
                project.account_id,
                project.id,
                {"attempt_id": attempt.id},
            )
            self._notify(db, project, attempt, published=False)
            return {**attempt_repo.public_attempt_view(attempt), "live_calls": True}

        ext_id, ext_url = self._extract_external_refs(db, post.id)
        if published:
            attempt_repo.mark_published(db, attempt, ext_id, ext_url, response_summary)
            self._write_audit(
                db,
                audit_actions.ACTION_TELEGRAM_LIVE_ROLLOUT_PUBLISHED,
                project.account_id,
                project.id,
                {"attempt_id": attempt.id, "post_id": post.id},
            )
            self._notify(db, project, attempt, published=True)
        else:
            attempt_repo.mark_failed(
                db, attempt, error_message="publish_failed", response_summary=response_summary
            )
            self._write_audit(
                db,
                audit_actions.ACTION_TELEGRAM_LIVE_ROLLOUT_FAILED,
                project.account_id,
                project.id,
                {"attempt_id": attempt.id},
            )
            self._notify(db, project, attempt, published=False)
        return {**attempt_repo.public_attempt_view(attempt), "live_calls": True}

    # ------------------------------------------------------------------ #
    # Attempts                                                           #
    # ------------------------------------------------------------------ #

    def list_attempts(
        self, db: Session, project_id: int, limit: int = 100, offset: int = 0
    ) -> dict[str, Any]:
        """Список попыток проекта (без секретов)."""
        self._require_project(db, project_id)
        attempts = attempt_repo.list_attempts_for_project(
            db, project_id, limit=limit, offset=offset
        )
        return {
            "project_id": project_id,
            "attempts": [attempt_repo.public_attempt_view(a) for a in attempts],
            "summary": attempt_repo.build_project_attempt_summary(db, project_id),
        }

    def get_attempt_detail(self, db: Session, attempt_id: int) -> dict[str, Any]:
        """Детали попытки (для API — доступ проверяется через attempt.project_id)."""
        attempt = attempt_repo.get_attempt_by_id(db, attempt_id)
        if attempt is None:
            raise TelegramLiveRolloutError("Попытка не найдена")
        return attempt_repo.public_attempt_view(attempt)

    def notify_attempt_result(self, db: Session, attempt: Any) -> None:
        """Уведомить о результате попытки (мягко; не роняет rollout)."""
        project = project_repository.get_project_by_id(db, attempt.project_id)
        if project is not None:
            self._notify(db, project, attempt, published=(attempt.status == "published"))

    # ------------------------------------------------------------------ #
    # Внутреннее: гейты/блокеры                                          #
    # ------------------------------------------------------------------ #

    def _publish_blockers(
        self,
        db: Session,
        project_id: int,
        status: dict[str, Any],
        post: Any,
        confirmation: str | None,
        settings: Any,
    ) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        # 1) Rollout kill-switch (allow_real_send).
        if not settings.telegram_live_rollout_allow_real_send_effective:
            blockers.append(
                self._blk("external_call_blocked", "Реальная отправка выключена (rollout).")
            )
        # 2) Глобальный флаг + клиентские гейты (из effective gate).
        for reason in status["blocked_reasons"]:
            if reason == "rollout_real_send_disabled":
                continue
            blockers.append(self._blk(reason, self._reason_message(reason)))
        # 3) Подтверждение.
        expected = settings.telegram_live_rollout_confirmation_text_safe
        if settings.telegram_live_rollout_require_confirmation_effective and (
            str(confirmation or "").strip() != expected
        ):
            blockers.append(
                self._blk("safety_gate_failed", f"Введите подтверждение «{expected}».")
            )
        # 4) Пост.
        if post is None:
            blockers.append(self._blk("post_missing", "Нет поста для публикации."))
        # 5) Дубликат.
        elif self._is_duplicate(db, project_id, post.id):
            blockers.append(
                self._blk("duplicate_attempt", "Этот пост уже публиковался в Telegram.")
            )
        return blockers

    def _is_duplicate(self, db: Session, project_id: int, post_id: int) -> bool:
        settings = self._resolve_settings()
        max_attempts = int(settings.telegram_live_rollout_max_attempts_per_post_safe)
        prior = [
            a
            for a in attempt_repo.list_attempts_for_post(db, post_id)
            if a.platform_key == _PLATFORM and a.status in ("attempted", "published")
        ]
        return len(prior) >= max_attempts

    def _status_blockers(
        self, status: dict[str, Any], tg_platform: dict[str, Any]
    ) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        if not tg_platform.get("token_present"):
            blockers.append(self._blk("telegram_token_missing", "Не подключён Telegram-токен."))
        if not tg_platform.get("channel_present"):
            blockers.append(self._blk("telegram_channel_missing", "Не указан канал Telegram."))
        for reason in status["blocked_reasons"]:
            if reason == "rollout_real_send_disabled":
                continue
            blockers.append(self._blk(reason, self._reason_message(reason)))
        return blockers

    # ------------------------------------------------------------------ #
    # Внутреннее: сигналы/пейлоад                                        #
    # ------------------------------------------------------------------ #

    def _telegram_platform_status(self, db: Session, project_id: int) -> dict[str, Any]:
        conn = self._connection(db, project_id, _PLATFORM)
        return {
            "connected": bool(conn and conn.get("connected")),
            "token_present": bool(conn and conn.get("api_key_present")),
            "channel_present": bool(conn and conn.get("external_id")),
        }

    def _safe_payload_preview(self, db: Session, post_id: int) -> dict[str, Any]:
        """Безопасный summary Telegram-пейлоада (без текста/пути/таргета)."""
        settings = self._resolve_settings()
        if not settings.telegram_live_rollout_record_payload_preview:
            return {"recorded": False}
        try:
            preview = self._publication_service().preview_publication(db, post_id)
            item = next((i for i in preview.items if i.platform == _PLATFORM), None)
            if item is None:
                return {"available": False}
            return {
                "available": True,
                "text_length": len(getattr(item, "text", "") or ""),
                "hashtag_count": len(getattr(item, "hashtags", []) or []),
                "media_count": int(getattr(item, "media_count", 0) or 0),
                "media_kind": getattr(item, "media_kind", "none"),
                "would_attach_media": bool(getattr(item, "would_attach_media", False)),
                "would_send": bool(getattr(item, "would_send", False)),
                "target_present": bool(getattr(item, "target_id", None)),
                "credentials_source": getattr(item, "credentials_source", "missing"),
                "token_present": bool(getattr(item, "token_present", False)),
            }
        except Exception:  # noqa: BLE001 — превью не критично
            return {"available": False}

    def _extract_external_refs(self, db: Session, post_id: int) -> tuple[str | None, str | None]:
        try:
            pub = post_publication_repository.get_publication_by_post_and_platform(
                db, post_id, _PLATFORM
            )
            if pub is not None:
                return (
                    str(pub.external_post_id) if pub.external_post_id else None,
                    pub.external_url,
                )
        except Exception:  # noqa: BLE001
            pass
        return None, None

    def _resolve_post(
        self, db: Session, project_id: int, post_id: int | None, publication_id: int | None
    ) -> Any:
        if post_id is not None:
            post = post_repository.get_post_by_id(db, post_id)
            return post if post and post.project_id == project_id else None
        if publication_id is not None:
            pub = post_publication_repository.get_publication_by_id(db, publication_id)
            if pub is not None and pub.project_id == project_id:
                return post_repository.get_post_by_id(db, pub.post_id)
            return None
        # Ни поста, ни публикации — берём свежий пост проекта (для preview/дашборда).
        recent = post_repository.list_recent_posts(db, project_id, limit=1)
        return recent[0] if recent else None

    # ------------------------------------------------------------------ #
    # Внутреннее: представление                                          #
    # ------------------------------------------------------------------ #

    def _gate_fields(self, status: dict[str, Any]) -> dict[str, Any]:
        return {
            "global_live_enabled": status["global_live_enabled"],
            "project_live_enabled": status["project_live_enabled"],
            "platform_live_enabled": status["platform_live_enabled"],
            "full_auto_live_enabled": status["full_auto_live_enabled"],
            "readiness_ready": status["readiness_ready"],
        }

    @staticmethod
    def _rollout_status(status: dict[str, Any], blockers: list[dict[str, Any]]) -> str:
        if status["can_send_real"]:
            return "enabled"
        if status["can_attempt_live"]:
            return "ready"  # всё готово, но реальная отправка ещё выключена (allow_real_send)
        if blockers:
            return "blocked"
        return "draft"

    def _next_action(self, status: dict[str, Any], tg_platform: dict[str, Any]) -> dict[str, Any]:
        if not tg_platform.get("connected"):
            return {"action": "connect_telegram", "label": "Подключите Telegram"}
        if not status["readiness_ready"]:
            return {"action": "open_live_readiness", "label": "Проверьте готовность к публикации"}
        if status["can_attempt_live"] and not status["rollout_allow_real_send"]:
            return {"action": "run_dry", "label": "Сделайте тестовый запуск без отправки"}
        if status["can_send_real"]:
            return {"action": "publish_once", "label": "Можно пробовать live"}
        return {"action": "open_live_readiness", "label": "Откройте готовность к автопубликации"}

    @staticmethod
    def _client_summary(rollout_status: str, status: dict[str, Any]) -> dict[str, Any]:
        headline = {
            "enabled": "Telegram live: включён",
            "ready": "Telegram: готов, реальная отправка выключена",
            "blocked": "Telegram: нужно исправить",
            "draft": "Telegram: не настроен",
        }.get(rollout_status, "Telegram: проверьте настройку")
        return {"headline": headline, "tone": rollout_status}

    @staticmethod
    def _reason_message(reason: str) -> str:
        return {
            "global_live_flag_disabled": "Условия публикации выключены администратором.",
            "project_live_disabled": "Live для проекта не включён.",
            "platform_live_disabled": "Live для Telegram не включён.",
            "full_auto_live_disabled": "Full-auto live не включён.",
            "readiness_not_ready": "Проект ещё не готов к публикации.",
        }.get(reason, reason)

    @staticmethod
    def _blk(blocker_type: str, message: str) -> dict[str, Any]:
        return {"type": blocker_type, "message": message}

    # ------------------------------------------------------------------ #
    # Внутреннее: notifications                                          #
    # ------------------------------------------------------------------ #

    def _notify(self, db: Session, project: Any, attempt: Any, published: bool) -> None:
        settings = self._resolve_settings()
        if published and not settings.telegram_live_rollout_notify_on_published:
            return
        if not published and not settings.telegram_live_rollout_notify_on_blocked:
            return
        try:
            owner_id = self._owner_user_id(db, project)
            if owner_id is None:
                return
            title = (
                "Telegram: пост опубликован" if published else "Telegram: публикация заблокирована"
            )
            message = (
                "Автопилот опубликовал пост в Telegram."
                if published
                else "Автопилот подготовил пост, но реальная публикация пока недоступна."
            )
            self._notification_service().create_notification(
                db,
                recipient_user_id=owner_id,
                notification_type="telegram_live_rollout",
                title=title,
                message=message,
                account_id=project.account_id,
                project_id=project.id,
                priority="normal",
                action_url=f"/ui/projects/{project.id}/telegram-live-rollout",
                metadata={"attempt_id": attempt.id, "status": attempt.status},
            )
        except Exception:  # noqa: BLE001 — уведомление не должно ронять rollout
            logger.warning("telegram rollout notify failed for project_id=%s", project.id)

    def _owner_user_id(self, db: Session, project: Any) -> int | None:
        if project is None or project.account_id is None:
            return None
        try:
            from app.repositories import account_repository

            account = account_repository.get_account_by_id(db, project.account_id)
            return getattr(account, "owner_user_id", None)
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------ #
    # Внутреннее: инфраструктура                                         #
    # ------------------------------------------------------------------ #

    def _require_project(self, db: Session, project_id: int) -> Any:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise TelegramLiveRolloutError("Проект не найден")
        return project

    def _connection(self, db: Session, project_id: int, platform_key: str) -> dict[str, Any] | None:
        try:
            from app.services.platform_connection_service import get_platform_connection_service

            conn: dict[str, Any] | None = get_platform_connection_service().get_connection(
                db, project_id, platform_key
            )
            return conn
        except Exception:  # noqa: BLE001
            return None

    def _autopost_cost(self) -> int:
        try:
            from app.services.billing_service import USAGE_AUTO_PUBLISH_ACTION

            return int(self._billing_service().estimate_action_cost(USAGE_AUTO_PUBLISH_ACTION))
        except Exception:  # noqa: BLE001
            return 5

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _readiness_service(self) -> Any:
        if self._readiness is None:
            from app.services.live_readiness_service import LiveReadinessService

            self._readiness = LiveReadinessService(settings=self._settings)
        return self._readiness

    def _publication_service(self) -> Any:
        if self._publication is None:
            from app.api.deps import (
                get_post_publication_service,
                get_publication_platform_registry,
            )

            self._publication = get_post_publication_service(get_publication_platform_registry())
        return self._publication

    def _billing_service(self) -> Any:
        if self._billing is None:
            from app.services.billing_service import BillingService

            self._billing = BillingService(settings=self._settings)
        return self._billing

    def _notification_service(self) -> Any:
        if self._notification is None:
            from app.services.notification_service import get_notification_service

            self._notification = get_notification_service()
        return self._notification

    def _audit_svc(self) -> AuditLogService:
        if self._audit is None:
            from app.services.audit_log_service import AuditLogService

            self._audit = AuditLogService()
        return self._audit

    def _write_audit(
        self,
        db: Session,
        action: str,
        account_id: int | None,
        project_id: int,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._audit_svc().record(
            db,
            action,
            account_id=account_id,
            project_id=project_id,
            entity_type="telegram_live_rollout",
            metadata=metadata or {},
        )


def get_telegram_live_rollout_service() -> TelegramLiveRolloutService:
    """DI-фабрика сервиса Telegram live rollout."""
    return TelegramLiveRolloutService()
