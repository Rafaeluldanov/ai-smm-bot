"""Сервис Telegram live production runbook — v0.6.3.

Клиентский «запуск Telegram автопилота»: агрегирует готовность (канал/media proxy/календарь/баланс/
live readiness/мониторинг), делает безопасный preview тестового поста и ручной production-тест.

БЕЗОПАСНОСТЬ (инварианты):
- runbook сам НЕ включает live и НЕ трогает глобальные ``*_LIVE_PUBLISHING_ENABLED``;
- реальная отправка ДЕЛЕГИРУЕТСЯ ``TelegramLiveRolloutService.publish_once_if_allowed`` — она
  возможна только под ВСЕМИ гейтами (global flag + project/platform/full_auto live + readiness +
  allow_real_send + подтверждение); runbook лишь оборачивает результат клиентской записью;
- preview ничего не отправляет; секретов/токенов/сырых payload не хранит (media_url — маскирован).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import project_repository
from app.repositories import telegram_live_runbook_repository as runbook_repo
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

_PLATFORM = "telegram"


class TelegramLiveRunbookError(Exception):
    """Ошибка Telegram runbook (нет проекта/поста/доступа) — API → 400/404."""


class TelegramLiveRunbookService:
    """Готовность + preview + ручной production-тест первого Telegram-канала."""

    def __init__(
        self,
        readiness_service: Any | None = None,
        rollout_service: Any | None = None,
        monitoring_service: Any | None = None,
        media_proxy_service: Any | None = None,
        publication_service: Any | None = None,
        platform_connection_service: Any | None = None,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._readiness = readiness_service
        self._rollout = rollout_service
        self._monitoring = monitoring_service
        self._media_proxy = media_proxy_service
        self._publication = publication_service
        self._platform_conn = platform_connection_service
        self._audit = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Чек-лист готовности                                                #
    # ------------------------------------------------------------------ #

    def build_checklist(
        self,
        db: Session,
        project_id: int,
        current_user_id: int | None = None,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        """Собрать чек-лист готовности Telegram-канала. При не-dry_run сохраняет runbook."""
        project = self._require_project(db, project_id)
        settings = self._resolve_settings()
        if dry_run is None:
            dry_run = settings.telegram_runbook_dry_run_effective

        # 1) Общая готовность автопилота (autopilot/calendar/media/balance/schedule/platforms/…).
        readiness = self._readiness_service().run_project_readiness_check(
            db, project_id, dry_run=True
        )
        rchecklist = readiness.get("checklist", {})
        # 2) Telegram-подключение (без сети): connected/token/channel_id.
        conn = self._platform_conn_svc().get_connection(db, project_id, _PLATFORM) or {}
        connected = bool(
            conn.get("connected") and conn.get("api_key_present") and conn.get("external_id")
        )
        channel_id = str(conn.get("external_id")) if conn.get("external_id") else None
        channel_name = str(conn.get("title")) if conn.get("title") else None
        # 3) Media proxy.
        mp = self._media_proxy_svc().validate_public_base_url()
        media_proxy_ready = bool(mp.get("enabled") and not mp.get("errors"))
        # 4) Мониторинг.
        monitoring_ready = bool(settings.live_autopilot_monitoring_enabled_effective)
        # 5) Эффективный gate (global+project+platform+full_auto+readiness) + allow_real_send.
        gate = self._rollout_svc().build_effective_telegram_live_status(db, project_id)
        # 6) Из readiness-чек-листа.
        calendar_ready = bool(rchecklist.get("calendar", {}).get("done"))
        balance_ready = bool(rchecklist.get("balance", {}).get("done"))
        readiness_ready = bool(gate.get("readiness_ready"))

        checklist = {
            "telegram": {"done": connected, "label": "Telegram канал"},
            "media_proxy": {"done": media_proxy_ready, "label": "Media Proxy"},
            "calendar": {"done": calendar_ready, "label": "Календарь"},
            "balance": {"done": balance_ready, "label": "Баланс"},
            "live_readiness": {"done": readiness_ready, "label": "Готовность к публикации"},
            "monitoring": {"done": monitoring_ready, "label": "Мониторинг"},
        }
        blockers = self._checklist_blockers(checklist, gate)
        warnings = list(readiness.get("warnings", []) or [])
        flags = {
            "connected": connected,
            "media_proxy_ready": media_proxy_ready,
            "calendar_ready": calendar_ready,
            "balance_ready": balance_ready,
            "readiness_ready": readiness_ready,
            "monitoring_ready": monitoring_ready,
        }
        ready = all(item["done"] for item in checklist.values())
        can_send_real = bool(gate.get("can_send_real"))
        status = self._runbook_status(ready, can_send_real, blockers)

        if not dry_run and settings.telegram_runbook_enabled_effective:
            # Явная проверка готовности переоценивает статус и СНИМАЕТ паузу (это осознанное
            # действие клиента). Обычный dry-run дашборд статус не трогает. Снятие паузы НЕ
            # включает реальную публикацию — она по-прежнему под всеми гейтами + подтверждением.
            runbook = runbook_repo.get_or_create(db, project_id, project.account_id)
            runbook_repo.update_checklist(
                db,
                runbook,
                checklist=checklist,
                blockers=blockers,
                warnings=warnings,
                flags=flags,
                channel_id=channel_id,
                channel_name=channel_name,
            )
            runbook_repo.update_status(db, runbook, status)
            self._write_audit(
                db,
                audit_actions.ACTION_TELEGRAM_RUNBOOK_CHECKED,
                project.account_id,
                project_id,
                {"ready": ready, "status": status, "blockers": len(blockers)},
            )

        return {
            "project_id": project_id,
            "ready": ready,
            "status": status,
            "checklist": checklist,
            "blockers": blockers,
            "warnings": warnings,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "can_send_real": can_send_real,
            "telegram_live_status": gate,
            "confirmation_text": settings.telegram_live_rollout_confirmation_text_safe,
            "dry_run": bool(dry_run),
            "note": (
                "Готовность — это чек-лист. Реальная публикация возможна только под всеми гейтами "
                "и с подтверждением; runbook сам live не включает."
            ),
        }

    def build_dashboard(self, db: Session, project_id: int) -> dict[str, Any]:
        """Клиентский дашборд runbook (без записи): чек-лист + статус + история попыток."""
        project = self._require_project(db, project_id)
        runbook = runbook_repo.get_or_create(db, project_id, project.account_id)
        checklist = self.build_checklist(db, project_id, dry_run=True)
        attempts = runbook_repo.list_attempts(db, project_id, limit=10)
        return {
            "project_id": project_id,
            "runbook": runbook_repo.public_runbook_view(runbook),
            "ready": checklist["ready"],
            "status": checklist["status"],
            "checklist": checklist["checklist"],
            "blockers": checklist["blockers"],
            "warnings": checklist["warnings"],
            "channel_id": checklist["channel_id"],
            "channel_name": checklist["channel_name"],
            "can_send_real": checklist["can_send_real"],
            "telegram_live_status": checklist["telegram_live_status"],
            "confirmation_text": checklist["confirmation_text"],
            "recent_attempts": [runbook_repo.public_attempt_view(a) for a in attempts],
            "note": checklist["note"],
        }

    # ------------------------------------------------------------------ #
    # Preview тестового поста (без отправки)                             #
    # ------------------------------------------------------------------ #

    def prepare_test_post(
        self,
        db: Session,
        project_id: int,
        post_id: int | None = None,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Собрать preview тестового поста (text/media_url/hashtags) БЕЗ отправки."""
        project = self._require_project(db, project_id)
        runbook = runbook_repo.get_or_create(db, project_id, project.account_id)
        post = self._resolve_post(db, project_id, post_id)
        if post is None:
            raise TelegramLiveRunbookError("Нет поста для тестовой публикации")

        text, hashtags, media_asset_id, media_count = self._preview_content(db, post)
        media_url_masked = None
        if media_asset_id is not None and self._resolve_settings().media_proxy_enabled_effective:
            with _soft():
                # Короткий TTL для preview-ссылки (минимизируем публичную поверхность).
                result = self._media_proxy_svc().build_social_media_url(
                    db, project_id, media_asset_id, _PLATFORM, ttl_seconds=3600
                )
                # В payload сохраняем ТОЛЬКО маскированный URL (без raw-токена).
                media_url_masked = result.url_masked
        payload_preview = {
            "text_snippet": (text or "")[:280],
            "text_length": len(text or ""),
            "hashtags": list(hashtags or [])[:20],
            "media_asset_id": media_asset_id,
            "media_count": media_count,
            "media_url_masked": media_url_masked,
        }
        attempt = runbook_repo.create_attempt(
            db,
            account_id=project.account_id,
            project_id=project_id,
            runbook_id=runbook.id,
            post_id=post.id,
            status="preview",
            payload_preview=payload_preview,
        )
        self._write_audit(
            db,
            audit_actions.ACTION_TELEGRAM_RUNBOOK_PREVIEWED,
            project.account_id,
            project_id,
            {"post_id": post.id},
        )
        return {
            "attempt": runbook_repo.public_attempt_view(attempt),
            "post_id": post.id,
            "writes": True,  # создаётся запись preview; отправки/сети нет
            "live_calls": False,
            "note": "Предпросмотр тестового поста. Ничего не отправлено.",
        }

    # ------------------------------------------------------------------ #
    # Подтверждение + production-тест                                     #
    # ------------------------------------------------------------------ #

    def confirm_live_publish(
        self,
        db: Session,
        project_id: int,
        confirmation_text: str | None,
        post_id: int | None = None,
    ) -> dict[str, Any]:
        """Проверить, разрешена ли реальная публикация (подтверждение + все гейты). Не публикует."""
        self._require_project(db, project_id)
        settings = self._resolve_settings()
        gate = self._rollout_svc().build_effective_telegram_live_status(db, project_id)
        expected = settings.telegram_live_rollout_confirmation_text_safe
        blockers: list[dict[str, Any]] = []
        for reason in gate.get("blocked_reasons", []) or []:
            blockers.append({"type": reason, "message": _reason_message(reason)})
        if str(confirmation_text or "").strip() != expected:
            blockers.append(
                {"type": "safety_gate_failed", "message": f"Введите подтверждение «{expected}»."}
            )
        allowed = not blockers and bool(gate.get("can_send_real"))
        return {
            "project_id": project_id,
            "allowed": allowed,
            "blockers": blockers,
            "confirmation_text": expected,
            "can_send_real": bool(gate.get("can_send_real")),
            "note": (
                "Реальная публикация возможна только при всех гейтах и верном подтверждении."
                if not allowed
                else "Все условия выполнены — можно сделать один тестовый production-пост."
            ),
        }

    def publish_test_post(
        self,
        db: Session,
        project_id: int,
        post_id: int | None = None,
        confirmation_text: str | None = None,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Ручной production-тест: делегирует реальную отправку rollout-сервису (под всеми гейтами).

        Runbook НЕ обходит гейты — вся защита в ``publish_once_if_allowed``. Здесь только клиентская
        запись попытки поверх технического LivePublishAttempt + передача результата в мониторинг.
        """
        project = self._require_project(db, project_id)
        runbook = runbook_repo.get_or_create(db, project_id, project.account_id)
        if runbook.status == "paused":
            raise TelegramLiveRunbookError("Runbook на паузе — возобновите перед публикацией")
        post = self._resolve_post(db, project_id, post_id)
        attempt = runbook_repo.create_attempt(
            db,
            account_id=project.account_id,
            project_id=project_id,
            runbook_id=runbook.id,
            post_id=post.id if post is not None else None,
            status="sending",
            confirmation_text=(str(confirmation_text or "").strip() or None),
        )
        # ДЕЛЕГИРУЕМ реальную публикацию под всеми гейтами существующему сервису.
        try:
            result = self._rollout_svc().publish_once_if_allowed(
                db,
                project_id,
                post_id=post.id if post is not None else None,
                confirmation=confirmation_text,
                current_user_id=current_user_id,
            )
        except Exception as exc:  # noqa: BLE001 — не оставляем «sending»-попытку висящей
            runbook_repo.mark_failed(db, attempt, error_message=type(exc).__name__)
            raise
        live_attempt_id = result.get("id")
        live_status = result.get("status")
        if live_status == "published":
            runbook_repo.mark_published(
                db,
                attempt,
                external_post_id=result.get("external_post_id"),
                external_url=result.get("external_url"),
                live_publish_attempt_id=live_attempt_id,
            )
        elif live_status == "blocked":
            runbook_repo.mark_failed(
                db,
                attempt,
                error_message="blocked",
                status="blocked",
                live_publish_attempt_id=live_attempt_id,
            )
        else:
            runbook_repo.mark_failed(
                db,
                attempt,
                error_message=str(result.get("error_message") or live_status or "failed"),
                live_publish_attempt_id=live_attempt_id,
            )
        self._write_audit(
            db,
            audit_actions.ACTION_TELEGRAM_RUNBOOK_PUBLISH_TESTED,
            project.account_id,
            project_id,
            {"live_status": live_status, "published": live_status == "published"},
        )
        # Мониторинг читает LivePublishAttempt автоматически; обновляем снимок (best-effort).
        with _soft():
            self._monitoring_svc().run_health_check(db, project_id, dry_run=True)
        return {
            "attempt": runbook_repo.public_attempt_view(
                runbook_repo.get_attempt_by_id(db, attempt.id) or attempt
            ),
            "rollout_result": result,
            "published": live_status == "published",
            "live_calls": bool(result.get("live_calls")),
            "note": "Реальная отправка выполняется только под всеми гейтами rollout-сервиса.",
        }

    def pause_runbook(
        self, db: Session, project_id: int, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """Поставить runbook на паузу (блокирует production-тест до возобновления проверкой)."""
        project = self._require_project(db, project_id)
        runbook = runbook_repo.get_or_create(db, project_id, project.account_id)
        runbook_repo.update_status(db, runbook, "paused")
        self._write_audit(
            db,
            audit_actions.ACTION_TELEGRAM_RUNBOOK_PAUSED,
            project.account_id,
            project_id,
            {},
        )
        return {
            "ok": True,
            "project_id": project_id,
            "status": "paused",
            "note": (
                "Runbook на паузе: тестовые публикации заблокированы. "
                "Запустите «Проверить готовность», чтобы снять паузу."
            ),
        }

    def list_attempts(self, db: Session, project_id: int, limit: int = 50) -> dict[str, Any]:
        """История попыток production-теста (без секретов)."""
        self._require_project(db, project_id)
        attempts = runbook_repo.list_attempts(db, project_id, limit=limit)
        return {
            "project_id": project_id,
            "attempts": [runbook_repo.public_attempt_view(a) for a in attempts],
        }

    # ------------------------------------------------------------------ #
    # Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    def _preview_content(self, db: Session, post: Any) -> tuple[str, list[str], int | None, int]:
        """Достать text/hashtags/media_asset_id/media_count поста (тот же текст, что при отправке).

        Использует ``build_publish_request`` (dry-run, без сети и без реестра площадок) — это тот же
        текст/хэштеги, что уйдут в реальную публикацию.
        """
        req = self._publication_svc().build_publish_request(db, post, _PLATFORM, None)
        text = str(getattr(req, "text", "") or "")
        hashtags = list(getattr(req, "hashtags", []) or [])
        asset_ids = self._media_asset_ids(post)
        media_asset_id = asset_ids[0] if asset_ids else None
        return text, hashtags, media_asset_id, len(asset_ids)

    @staticmethod
    def _media_asset_ids(post: Any) -> list[int]:
        """id медиа-активов поста (из generation_notes.media_asset_ids или media_asset_id)."""
        notes = getattr(post, "generation_notes", None) or {}
        ids = notes.get("media_asset_ids") if isinstance(notes, dict) else None
        result: list[int] = []
        if isinstance(ids, list):
            result = [v for v in ids if isinstance(v, int)]
        if not result and getattr(post, "media_asset_id", None) is not None:
            result = [int(post.media_asset_id)]
        return result

    def _resolve_post(self, db: Session, project_id: int, post_id: int | None) -> Any:
        from app.repositories import post_repository

        if post_id is not None:
            post = post_repository.get_post_by_id(db, post_id)
            if post is None or post.project_id != project_id:
                raise TelegramLiveRunbookError("Пост не найден")
            return post
        recent = post_repository.list_recent_posts(db, project_id, limit=1)
        return recent[0] if recent else None

    @staticmethod
    def _checklist_blockers(
        checklist: dict[str, Any], gate: dict[str, Any]
    ) -> list[dict[str, Any]]:
        messages = {
            "telegram": "Подключите Telegram-канал (бот-токен + channel_id).",
            "media_proxy": "Настройте публичный домен доставки медиа (media proxy).",
            "calendar": "Настройте календарь публикаций.",
            "balance": "Пополните баланс.",
            "live_readiness": "Пройдите проверку готовности к автопубликации.",
            "monitoring": "Включите мониторинг автопилота.",
        }
        blockers: list[dict[str, Any]] = [
            {"type": key, "message": messages.get(key, key)}
            for key, item in checklist.items()
            if not item.get("done")
        ]
        return blockers

    @staticmethod
    def _runbook_status(ready: bool, can_send_real: bool, blockers: list[Any]) -> str:
        if blockers:
            return "blocked"
        if ready and can_send_real:
            return "enabled"
        if ready:
            return "ready"
        return "draft"

    def _require_project(self, db: Session, project_id: int) -> Any:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise TelegramLiveRunbookError("Проект не найден")
        return project

    def _resolve_settings(self) -> Settings:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _readiness_service(self) -> Any:
        if self._readiness is None:
            from app.services.live_readiness_service import LiveReadinessService

            self._readiness = LiveReadinessService(settings=self._resolve_settings())
        return self._readiness

    def _rollout_svc(self) -> Any:
        if self._rollout is None:
            from app.services.telegram_live_rollout_service import TelegramLiveRolloutService

            self._rollout = TelegramLiveRolloutService(settings=self._resolve_settings())
        return self._rollout

    def _monitoring_svc(self) -> Any:
        if self._monitoring is None:
            from app.services.live_autopilot_monitoring_service import (
                LiveAutopilotMonitoringService,
            )

            self._monitoring = LiveAutopilotMonitoringService(settings=self._resolve_settings())
        return self._monitoring

    def _media_proxy_svc(self) -> Any:
        if self._media_proxy is None:
            from app.services.media_proxy_service import MediaProxyService

            self._media_proxy = MediaProxyService(settings=self._resolve_settings())
        return self._media_proxy

    def _publication_svc(self) -> Any:
        if self._publication is None:
            from app.services.post_publication_service import PostPublicationService
            from app.services.publication_platform_registry import PublicationPlatformRegistry

            # Пустой реестр: preview_publication НЕ вызывает клиентов (dry-run, без сети).
            self._publication = PostPublicationService(registry=PublicationPlatformRegistry({}))
        return self._publication

    def _platform_conn_svc(self) -> Any:
        if self._platform_conn is None:
            from app.services.platform_connection_service import PlatformConnectionService

            self._platform_conn = PlatformConnectionService()
        return self._platform_conn

    def _audit_svc(self) -> AuditLogService:
        if self._audit is None:
            from app.services.audit_log_service import AuditLogService

            self._audit = AuditLogService(self._resolve_settings())
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
            entity_type="telegram_live_runbook",
            metadata=metadata or {},
        )


class _soft:
    """Контекст «мягкого» вызова: побочный сбой (media proxy/monitoring) не роняет поток."""

    def __enter__(self) -> _soft:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if exc_type is not None:
            logger.warning("telegram-runbook soft call failed: %s", exc_type.__name__)
        return True


def _reason_message(reason: str) -> str:
    return {
        "global_live_flag_disabled": "Реальная публикация выключена администратором (глобально).",
        "project_live_disabled": "Live для проекта не включён.",
        "platform_live_disabled": "Live для Telegram не включён.",
        "full_auto_live_disabled": "Полностью автоматический режим не включён.",
        "readiness_not_ready": "Проект не прошёл проверку готовности.",
        "rollout_real_send_disabled": "Реальная отправка выключена (rollout).",
    }.get(reason, reason)


def get_telegram_live_runbook_service() -> TelegramLiveRunbookService:
    """DI-фабрика сервиса Telegram runbook."""
    return TelegramLiveRunbookService()
