"""Сервис авто-синхронизации Яндекс Диска — v0.5.7.

Клиент загружает картинки в папку Яндекс Диска — Botfleet сам находит новые файлы и готовит
медиатеку для автопостинга: sync → базовые теги → quality scoring → fingerprint/dedup → curation
preview. Тонкий оркестратор поверх существующих подсистем (public media sync, media quality,
fingerprint, curation, autopilot).

БЕЗОПАСНОСТЬ:
- РЕАЛЬНАЯ сеть выключена по умолчанию (``YANDEX_AUTO_SYNC_NETWORK_ENABLED=false``) — реальный
  sync-сервис вообще не создаётся, пока сеть не разрешена явно;
- dry-run по умолчанию — без записи медиа;
- файлы НИКОГДА не удаляются и не скрываются;
- секретов/сырых токенов/внутренних путей наружу нет; public_url — только маской.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.core.redaction import redact_sensitive_text
from app.repositories import (
    media_asset_repository,
    project_repository,
)
from app.repositories import (
    yandex_auto_sync_repository as sync_repo,
)
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.project_yandex_sync_profile import ProjectYandexSyncProfile
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".heic")
_VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v")


class YandexAutoSyncError(Exception):
    """Ошибка авто-синхронизации (нет проекта/доступа/невалидные данные) — API → 400/404."""


def _now() -> datetime:
    return datetime.now(UTC)


class YandexAutoSyncService:
    """Оркестратор авто-синхронизации Яндекс Диска: профиль, health, preview, run, worker-tick."""

    def __init__(
        self,
        public_sync_service: Any = None,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._public_sync = public_sync_service
        self._audit = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Профиль                                                            #
    # ------------------------------------------------------------------ #

    def get_or_create_profile(
        self, db: Session, project_id: int, current_user_id: int | None = None
    ) -> ProjectYandexSyncProfile:
        """Получить/создать профиль синхронизации; подтянуть данные из autopilot/CrmSmmResource."""
        project = self._require_project(db, project_id)
        created = sync_repo.get_profile_by_project_id(db, project_id) is None
        profile = sync_repo.get_or_create_profile(
            db,
            account_id=project.account_id,
            project_id=project_id,
            current_user_id=current_user_id,
        )
        if created:
            self._hydrate_from_existing(db, project_id, profile)
            self._write_audit(db, audit_actions.ACTION_YANDEX_SYNC_PROFILE_CREATED, profile, {})
        return profile

    def configure_profile(
        self,
        db: Session,
        project_id: int,
        payload: dict[str, Any],
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Сохранить настройки профиля (public_url/root_folder/теги/частота/включение)."""
        profile = self.get_or_create_profile(db, project_id, current_user_id)
        fields: dict[str, Any] = {"updated_by_user_id": current_user_id}
        if "public_url" in payload:
            fields["public_url"] = str(payload.get("public_url") or "").strip() or None
        if "root_folder" in payload:
            fields["root_folder"] = str(payload.get("root_folder") or "SMM").strip() or "SMM"
        if "default_tags" in payload:
            fields["default_tags"] = [
                str(t).strip() for t in (payload.get("default_tags") or []) if str(t).strip()
            ][:50]
        if "allowed_folders" in payload:
            fields["allowed_folders"] = [
                str(f).strip() for f in (payload.get("allowed_folders") or []) if str(f).strip()
            ][:50]
        if "sync_frequency_minutes" in payload:
            freq = int(payload.get("sync_frequency_minutes") or 60)
            fields["sync_frequency_minutes"] = max(5, min(1440, freq))
        if "is_enabled" in payload:
            fields["is_enabled"] = bool(payload.get("is_enabled"))
        sync_repo.update_profile(db, profile, fields)
        # Подсинхронизировать autopilot yandex_resource_id, если возможно (без секретов).
        self._link_autopilot(db, project_id, profile)
        self._write_audit(
            db,
            audit_actions.ACTION_YANDEX_SYNC_PROFILE_UPDATED,
            profile,
            {"root_folder": profile.root_folder, "frequency": profile.sync_frequency_minutes},
        )
        return sync_repo.public_profile_view(profile)

    def pause_sync(
        self, db: Session, project_id: int, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """Поставить синхронизацию на паузу."""
        profile = self.get_or_create_profile(db, project_id, current_user_id)
        sync_repo.update_profile(
            db,
            profile,
            {"is_enabled": False, "status": "paused", "updated_by_user_id": current_user_id},
        )
        self._write_audit(db, audit_actions.ACTION_YANDEX_SYNC_PAUSED, profile, {})
        return sync_repo.public_profile_view(profile)

    def resume_sync(
        self, db: Session, project_id: int, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """Возобновить синхронизацию."""
        profile = self.get_or_create_profile(db, project_id, current_user_id)
        sync_repo.update_profile(
            db,
            profile,
            {"is_enabled": True, "status": "ready", "updated_by_user_id": current_user_id},
        )
        self._write_audit(db, audit_actions.ACTION_YANDEX_SYNC_RESUMED, profile, {})
        return sync_repo.public_profile_view(profile)

    # ------------------------------------------------------------------ #
    # Health check / dashboard                                           #
    # ------------------------------------------------------------------ #

    def health_check(self, db: Session, project_id: int) -> dict[str, Any]:
        """Проверить готовность синхронизации и вернуть блокеры (без побочных эффектов)."""
        profile = self.get_or_create_profile(db, project_id)
        settings = self._resolve_settings()
        media_count = media_asset_repository.count_media_assets(db, project_id=project_id)
        blockers: list[dict[str, Any]] = []

        if not (profile.public_url or "").strip():
            blockers.append(
                self._blocker("no_yandex_disk", "setup", "Дайте ссылку на Яндекс Диск.", "sync_now")
            )
        elif not self._looks_like_yandex_url(profile.public_url):
            blockers.append(
                self._blocker(
                    "invalid_public_url",
                    "setup",
                    "Ссылка не похожа на публичную ссылку Яндекс Диска.",
                    "sync_now",
                )
            )
        if not (profile.root_folder or "").strip():
            blockers.append(
                self._blocker(
                    "unsupported_folder",
                    "info",
                    "Укажите папку с картинками (например SMM).",
                    "sync_now",
                )
            )
        if media_count <= 0:
            blockers.append(
                self._blocker(
                    "no_media_found",
                    "setup",
                    "В медиатеке пока нет картинок — загрузите фото и синхронизируйте.",
                    "sync_now",
                )
            )
        elif media_count < settings.yandex_auto_sync_min_media_assets_safe:
            blockers.append(
                self._blocker(
                    "too_few_media",
                    "info",
                    f"Мало картинок ({media_count}). Рекомендуем от "
                    f"{settings.yandex_auto_sync_recommended_media_assets_safe}.",
                    "sync_now",
                )
            )
        if not profile.is_enabled:
            blockers.append(
                self._blocker("sync_disabled", "info", "Синхронизация на паузе.", "resume")
            )
        if not settings.yandex_auto_sync_network_enabled_effective:
            blockers.append(
                self._blocker(
                    "network_disabled",
                    "info",
                    "Тестовый режим: внешняя сеть выключена — синхронизация не выполняется.",
                    "refresh_status",
                )
            )

        status = self._status_from_blockers(profile, blockers)
        sync_repo.update_profile(
            db,
            profile,
            {"active_blockers": blockers, "status": status if profile.is_enabled else "paused"},
        )
        return {
            "project_id": project_id,
            "status": status,
            "blockers": blockers,
            "media_count": media_count,
            "has_public_url": bool((profile.public_url or "").strip()),
            "next_best_action": self._next_best_action(blockers),
        }

    def build_dashboard(self, db: Session, project_id: int) -> dict[str, Any]:
        """Клиентский дашборд синхронизации (без технического жаргона)."""
        _s = self._resolve_settings()
        profile = self.get_or_create_profile(db, project_id)
        health = self.health_check(db, project_id)
        counts = self._media_counts(db, project_id)
        runs = sync_repo.list_runs_for_project(db, project_id, limit=10)
        quality = self._quality_summary(db, project_id)
        return {
            "profile": sync_repo.public_profile_view(profile),
            "status": health["status"],
            "media_count": counts["total"],
            "image_count": counts["images"],
            "video_count": counts["videos"],
            "last_sync": {
                "status": profile.last_sync_status,
                "at": profile.last_sync_at.isoformat() if profile.last_sync_at else None,
                "summary": dict(profile.last_sync_summary or {}),
            },
            "next_sync": profile.next_sync_at.isoformat() if profile.next_sync_at else None,
            "blockers": health["blockers"],
            "next_best_action": health["next_best_action"],
            "recent_runs": [sync_repo.public_run_view(r) for r in runs],
            "quality_summary": quality,
            "duplicate_summary": {"duplicates": (quality or {}).get("duplicates", 0)},
            "curation_summary": self._curation_summary(db, project_id),
            "simple_client_summary": self.build_client_summary(db, project_id),
            "flags": {
                "enabled": _s.yandex_auto_sync_enabled_effective,
                "worker_enabled": _s.yandex_auto_sync_worker_enabled_effective,
                "dry_run": _s.yandex_auto_sync_dry_run_effective,
                "network_enabled": _s.yandex_auto_sync_network_enabled_effective,
                "auto_delete": _s.yandex_auto_sync_auto_delete,
            },
        }

    # ------------------------------------------------------------------ #
    # Preview / run                                                      #
    # ------------------------------------------------------------------ #

    def preview_sync(
        self,
        db: Session,
        project_id: int,
        limit: int | None = None,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Предпросмотр синхронизации (без записи, без сети по умолчанию)."""
        profile = self.get_or_create_profile(db, project_id, current_user_id)
        settings = self._resolve_settings()
        counts = self._media_counts(db, project_id)
        self._write_audit(db, audit_actions.ACTION_YANDEX_SYNC_PREVIEWED, profile, {})
        return {
            "project_id": project_id,
            "dry_run": True,
            "network_enabled": settings.yandex_auto_sync_network_enabled_effective,
            "would_sync": not settings.yandex_auto_sync_network_enabled_effective,
            "public_url_masked": self.mask_public_url(profile.public_url),
            "root_folder": profile.root_folder,
            "current_media": counts,
            "note": (
                "Тестовый режим: внешняя сеть выключена. Показано текущее состояние медиатеки; "
                "реальная синхронизация не выполняется."
                if not settings.yandex_auto_sync_network_enabled_effective
                else "Синхронизация проверит Яндекс Диск и найдёт новые картинки."
            ),
            "writes": False,
        }

    def run_sync(
        self,
        db: Session,
        project_id: int,
        dry_run: bool = True,
        current_user_id: int | None = None,
        idempotency_key: str | None = None,
        worker_owner_id: str | None = None,
    ) -> dict[str, Any]:
        """Запустить синхронизацию (dry-run по умолчанию; реальная — только при network)."""
        project = self._require_project(db, project_id)
        profile = self.get_or_create_profile(db, project_id, current_user_id)
        settings = self._resolve_settings()

        if idempotency_key:
            existing = sync_repo.get_run_by_idempotency_key(db, idempotency_key)
            if existing is not None:
                return sync_repo.public_run_view(existing)

        run = sync_repo.create_run(
            db,
            account_id=project.account_id,
            project_id=project_id,
            sync_profile_id=profile.id,
            autopilot_profile_id=profile.autopilot_profile_id,
            status="started",
            source_type=profile.source_type,
            public_url_masked=self.mask_public_url(profile.public_url),
            root_folder=profile.root_folder,
            dry_run=dry_run,
            idempotency_key=idempotency_key,
            created_by_worker_owner_id=worker_owner_id,
            started_at=_now(),
        )
        self._write_audit(db, audit_actions.ACTION_YANDEX_SYNC_STARTED, profile, {"run_id": run.id})

        # Гейт безопасности: реальная синхронизация только при network + не dry_run.
        do_real = bool(not dry_run and settings.yandex_auto_sync_network_enabled_effective)
        summary: dict[str, Any] = {}
        blockers: list[dict[str, Any]] = []
        warnings: list[str] = []
        try:
            if do_real:
                summary = self._real_sync(db, project_id)
            else:
                # Dry-run/network off: без записи медиа. Просто фиксируем текущее состояние.
                if not dry_run and not settings.yandex_auto_sync_network_enabled_effective:
                    blockers.append(
                        self._blocker(
                            "network_disabled",
                            "info",
                            "Внешняя сеть выключена — синхронизация выполнена в безопасном режиме.",
                            "refresh_status",
                        )
                    )
                summary = {"files_seen": 0, "files_imported": 0, "files_updated": 0}
            # Пост-обработка медиатеки (quality/fingerprint/curation) — без сети, без удаления.
            post = self._post_process(db, project_id, write=do_real)
            summary.update(post)
        except Exception as exc:  # noqa: BLE001 — сбой не роняет; ошибка санитизируется
            logger.warning("yandex sync failed for project_id=%s", project_id)
            sync_repo.mark_failed(db, run, _sanitize(str(exc)))
            self._update_profile_after_run(db, profile, "failed", summary, blockers)
            self._write_audit(
                db, audit_actions.ACTION_YANDEX_SYNC_FAILED, profile, {"run_id": run.id}
            )
            return sync_repo.public_run_view(run)

        counts = self._media_counts(db, project_id)
        final_status = self._run_status(summary, blockers, dry_run, do_real)
        run_fields = {
            "files_seen": int(summary.get("files_seen", 0)),
            "files_imported": int(summary.get("files_imported", 0)),
            "files_updated": int(summary.get("files_updated", 0)),
            "files_skipped": int(summary.get("files_skipped", 0)),
            "files_failed": int(summary.get("files_failed", 0)),
            "media_assets_created": int(summary.get("files_imported", 0)),
            "media_assets_updated": int(summary.get("files_updated", 0)),
            "quality_snapshots_created": int(summary.get("quality_snapshots_created", 0)),
            "fingerprints_created": int(summary.get("fingerprints_created", 0)),
            "curation_tasks_created": int(summary.get("curation_tasks_created", 0)),
            "blockers": blockers,
            "warnings": warnings,
        }
        sync_repo.mark_finished(db, run, final_status, run_fields)
        self._update_profile_after_run(db, profile, final_status, {**summary, **counts}, blockers)
        self._write_audit(
            db,
            audit_actions.ACTION_YANDEX_SYNC_COMPLETED,
            profile,
            {"run_id": run.id, "status": final_status},
        )
        return sync_repo.public_run_view(run)

    def run_worker_tick(
        self,
        db: Session,
        owner_id: str | None = None,
        dry_run: bool = True,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Один tick воркера синхронизации: обойти due-профили в безопасном режиме."""
        settings = self._resolve_settings()
        result: dict[str, Any] = {
            "enabled": settings.yandex_auto_sync_worker_enabled_effective,
            "dry_run": dry_run or settings.yandex_auto_sync_dry_run_effective,
            "profiles_scanned": 0,
            "runs_created": 0,
            "media_imported": 0,
            "errors": [],
        }
        if not settings.yandex_auto_sync_worker_enabled_effective:
            result["note"] = "Sync worker выключен (YANDEX_AUTO_SYNC_WORKER_ENABLED=false)."
            return result
        cap = limit or settings.yandex_auto_sync_max_projects_per_tick_safe
        profiles = sync_repo.list_due_profiles(db, now=_now(), limit=cap)
        effective_dry = dry_run or settings.yandex_auto_sync_dry_run_effective
        for profile in profiles:
            result["profiles_scanned"] += 1
            try:
                run = self.run_sync(
                    db, profile.project_id, dry_run=effective_dry, worker_owner_id=owner_id
                )
                result["runs_created"] += 1
                result["media_imported"] += int(run.get("files_imported", 0))
            except Exception as exc:  # noqa: BLE001 — один проект не роняет весь tick
                result["errors"].append(_sanitize(str(exc))[:200])
        return result

    # ------------------------------------------------------------------ #
    # Клиентская сводка                                                  #
    # ------------------------------------------------------------------ #

    def build_client_summary(self, db: Session, project_id: int) -> dict[str, Any]:
        """Простая клиентская сводка: «Медиа готово / нужно добавить картинки / есть проблема»."""
        profile = self.get_or_create_profile(db, project_id)
        settings = self._resolve_settings()
        counts = self._media_counts(db, project_id)
        total = counts["total"]
        last = (
            f"Последняя проверка: {profile.last_sync_at.strftime('%d.%m %H:%M')}."
            if profile.last_sync_at
            else "Проверок ещё не было."
        )
        if not (profile.public_url or "").strip():
            headline, tone = "Дайте ссылку на Яндекс Диск", "setup"
        elif total <= 0:
            headline, tone = "Нужно добавить картинки", "setup"
        elif total < settings.yandex_auto_sync_min_media_assets_safe:
            headline, tone = f"Мало картинок ({total})", "attention"
        else:
            headline, tone = f"Медиа готово: {total} картинок", "ready"
        return {"headline": headline, "tone": tone, "detail": last}

    def mask_public_url(self, url: str | None) -> str | None:
        """Замаскировать публичную ссылку (домен + хвост)."""
        return sync_repo._mask_url(url)  # noqa: SLF001 — общая утилита маскирования

    # ------------------------------------------------------------------ #
    # Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    def _real_sync(self, db: Session, project_id: int) -> dict[str, Any]:
        """Реальная синхронизация через существующий public sync service (только за флагами)."""
        result = self._public_sync_service().sync_project_media_from_public_link(db, project_id)
        return {
            "files_seen": int(getattr(result, "found_files", 0) or 0),
            "files_imported": int(getattr(result, "created", 0) or 0),
            "files_updated": int(getattr(result, "updated", 0) or 0),
            "files_skipped": int(getattr(result, "skipped", 0) or 0),
            "files_failed": len(getattr(result, "errors", []) or []),
        }

    def _post_process(self, db: Session, project_id: int, write: bool) -> dict[str, Any]:
        """Quality scoring / fingerprint / curation preview после синхронизации (без удаления)."""
        settings = self._resolve_settings()
        out: dict[str, Any] = {}
        if settings.yandex_auto_sync_run_quality_scoring:
            try:
                q = self._quality_service().score_project_media(db, project_id, dry_run=not write)
                out["quality_snapshots_created"] = int(q.get("snapshots_created", 0))
            except Exception:  # noqa: BLE001 — не критично для синхронизации
                logger.warning("quality scoring failed for project_id=%s", project_id)
        if settings.yandex_auto_sync_run_fingerprinting:
            try:
                f = self._fingerprint_service().calculate_project_fingerprints(
                    db, project_id, dry_run=not write
                )
                out["fingerprints_created"] = int(f.get("created", 0))
            except Exception:  # noqa: BLE001
                logger.warning("fingerprinting failed for project_id=%s", project_id)
        if settings.yandex_auto_sync_run_curation_preview:
            try:
                c = self._curation_service().preview_curation_tasks(db, project_id)
                out["curation_tasks_created"] = int(c.get("tasks_found", 0))
            except Exception:  # noqa: BLE001
                logger.warning("curation preview failed for project_id=%s", project_id)
        return out

    def _update_profile_after_run(
        self,
        db: Session,
        profile: ProjectYandexSyncProfile,
        status: str,
        summary: dict[str, Any],
        blockers: list[dict[str, Any]],
    ) -> None:
        counts = self._media_counts(db, profile.project_id)
        next_sync = _now() + timedelta(minutes=profile.sync_frequency_minutes or 60)
        sync_repo.update_profile(
            db,
            profile,
            {
                "last_sync_at": _now(),
                "last_sync_status": status,
                "last_sync_summary": {
                    "files_seen": summary.get("files_seen", 0),
                    "files_imported": summary.get("files_imported", 0),
                    "files_updated": summary.get("files_updated", 0),
                },
                "next_sync_at": next_sync,
                "media_count": counts["total"],
                "image_count": counts["images"],
                "video_count": counts["videos"],
                "new_media_count": int(summary.get("files_imported", 0)),
                "updated_media_count": int(summary.get("files_updated", 0)),
                "failed_media_count": int(summary.get("files_failed", 0)),
                "active_blockers": blockers,
                "status": "ready" if profile.is_enabled else "paused",
            },
        )
        # Обновить autopilot health, если возможно (без live-эффектов).
        try:
            self._autopilot_service().run_health_check(db, profile.project_id)
        except Exception:  # noqa: BLE001 — обновление autopilot не критично
            logger.warning("autopilot health refresh failed for project_id=%s", profile.project_id)

    def _media_counts(self, db: Session, project_id: int) -> dict[str, int]:
        assets = media_asset_repository.list_media_assets_by_project(db, project_id=project_id)
        images = 0
        videos = 0
        for a in assets:
            name = (a.file_name or "").lower()
            if name.endswith(_IMAGE_EXTS):
                images += 1
            elif name.endswith(_VIDEO_EXTS):
                videos += 1
        return {"total": len(assets), "images": images, "videos": videos}

    def _quality_summary(self, db: Session, project_id: int) -> dict[str, Any] | None:
        try:
            d = self._quality_service().build_media_quality_dashboard(db, project_id)
            return {
                "good": d.get("good", 0),
                "excellent": d.get("excellent", 0),
                "weak": d.get("weak", 0),
                "duplicates": d.get("duplicates", 0),
            }
        except Exception:  # noqa: BLE001 — качество не критично для дашборда
            return None

    def _curation_summary(self, db: Session, project_id: int) -> dict[str, Any] | None:
        try:
            d = self._curation_service().build_curation_dashboard(db, project_id)
            return {
                "hidden": d.get("hidden_media_count", 0),
                "selectable": d.get("selectable_media_count", 0),
                "active_tasks": d.get("active_tasks", 0),
            }
        except Exception:  # noqa: BLE001
            return None

    def _hydrate_from_existing(
        self, db: Session, project_id: int, profile: ProjectYandexSyncProfile
    ) -> None:
        """Подтянуть public_url/root_folder из существующего CrmSmmResource (yandex_disk)."""
        try:
            from app.services.platform_connection_service import get_platform_connection_service

            conns = get_platform_connection_service().list_connections(db, project_id)
            yd = next((c for c in conns if c.get("platform_key") == "yandex_disk"), None)
            fields: dict[str, Any] = {}
            if yd:
                url = yd.get("public_media_url") or yd.get("url")
                if url and not (profile.public_url or "").strip():
                    fields["public_url"] = url
                if yd.get("root_folder") and not (profile.root_folder or "").strip():
                    fields["root_folder"] = yd.get("root_folder")
            if fields:
                sync_repo.update_profile(db, profile, fields)
        except Exception:  # noqa: BLE001 — hydration не критична
            logger.warning("yandex sync hydration failed for project_id=%s", project_id)

    def _link_autopilot(
        self, db: Session, project_id: int, profile: ProjectYandexSyncProfile
    ) -> None:
        """Связать профиль синхронизации с autopilot-профилем (без live-эффектов)."""
        try:
            from app.repositories import autopilot_repository

            ap = autopilot_repository.get_profile_by_project_id(db, project_id)
            if ap is not None and profile.autopilot_profile_id != ap.id:
                sync_repo.update_profile(db, profile, {"autopilot_profile_id": ap.id})
        except Exception:  # noqa: BLE001
            logger.warning("autopilot link failed for project_id=%s", project_id)

    @staticmethod
    def _status_from_blockers(profile: Any, blockers: list[dict[str, Any]]) -> str:
        if not profile.is_enabled:
            return "paused"
        if any(b["severity"] == "blocking" for b in blockers):
            return "blocked"
        if any(b["severity"] == "setup" for b in blockers):
            return "blocked"
        return "ready"

    @staticmethod
    def _run_status(
        summary: dict[str, Any], blockers: list[dict[str, Any]], dry_run: bool, do_real: bool
    ) -> str:
        if any(b["type"] == "network_disabled" for b in blockers) and not dry_run:
            return "blocked"
        if dry_run:
            return "preview"
        failed = int(summary.get("files_failed", 0))
        imported = int(summary.get("files_imported", 0))
        if failed and imported:
            return "partially_synced"
        if do_real:
            return "synced"
        return "skipped"

    def _next_best_action(self, blockers: list[dict[str, Any]]) -> dict[str, Any]:
        for severity in ("setup", "blocking", "info"):
            for b in blockers:
                if b["severity"] == severity:
                    return {"action": b["action"], "label": b["message"], "blocker": b["type"]}
        return {"action": "sync_now", "label": "Синхронизировать сейчас", "blocker": None}

    @staticmethod
    def _blocker(blocker_type: str, severity: str, message: str, action: str) -> dict[str, Any]:
        return {"type": blocker_type, "severity": severity, "message": message, "action": action}

    @staticmethod
    def _looks_like_yandex_url(url: str | None) -> bool:
        value = (url or "").strip().lower()
        return value.startswith(("http://", "https://")) and (
            "yandex" in value or "disk.yandex" in value or "yadi.sk" in value
        )

    def _require_project(self, db: Session, project_id: int) -> Any:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise YandexAutoSyncError("Проект не найден")
        return project

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _public_sync_service(self) -> Any:
        if self._public_sync is None:
            # Строим реальный sync-сервис (с сетевым клиентом) ТОЛЬКО в live-пути.
            from app.services.media_tagging_service import MediaTaggingService
            from app.services.public_yandex_disk_media_sync_service import (
                PublicYandexDiskMediaSyncService,
            )

            settings = self._resolve_settings()
            from app.integrations.yandex_disk.client import YandexDiskPublicClient

            client = YandexDiskPublicClient(base_url=settings.yandex_disk_base_url)
            self._public_sync = PublicYandexDiskMediaSyncService(
                client=client,
                tagging_service=MediaTaggingService(),
                public_key=settings.yandex_disk_public_smm_url or None,
                root_folder=settings.yandex_disk_public_root_folder,
            )
        return self._public_sync

    def _quality_service(self) -> Any:
        if getattr(self, "_quality_svc", None) is None:
            from app.services.media_quality_service import get_media_quality_service

            self._quality_svc = get_media_quality_service()
        return self._quality_svc

    def _fingerprint_service(self) -> Any:
        if getattr(self, "_fp_svc", None) is None:
            from app.services.media_fingerprint_service import get_media_fingerprint_service

            self._fp_svc = get_media_fingerprint_service()
        return self._fp_svc

    def _curation_service(self) -> Any:
        if getattr(self, "_cur_svc", None) is None:
            from app.services.media_curation_service import get_media_curation_service

            self._cur_svc = get_media_curation_service()
        return self._cur_svc

    def _autopilot_service(self) -> Any:
        if getattr(self, "_ap_svc", None) is None:
            from app.services.autopilot_service import AutopilotService

            self._ap_svc = AutopilotService(settings=self._settings)
        return self._ap_svc

    def _audit_svc(self) -> AuditLogService:
        if self._audit is None:
            from app.services.audit_log_service import AuditLogService

            self._audit = AuditLogService()
        return self._audit

    def _write_audit(
        self, db: Session, action: str, profile: Any, metadata: dict[str, Any] | None = None
    ) -> None:
        self._audit_svc().record(
            db,
            action,
            account_id=profile.account_id,
            project_id=profile.project_id,
            entity_type="yandex_sync_profile",
            entity_id=profile.id,
            metadata=metadata or {},
        )


def _sanitize(text: str | None) -> str:
    """Санитизировать текст ошибки (убрать секреты/токены/внутренние пути)."""
    cleaned = redact_sensitive_text(text or "")
    # Убрать возможные абсолютные пути.
    return os.path.basename(cleaned) if cleaned.startswith("/") else cleaned[:512]


def get_yandex_auto_sync_service() -> YandexAutoSyncService:
    """DI-фабрика сервиса авто-синхронизации Яндекс Диска."""
    return YandexAutoSyncService()
