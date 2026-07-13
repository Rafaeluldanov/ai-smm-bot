"""Сервис готовности к реальной автопубликации (live autopost readiness) — v0.5.9.

Production live autopost audit: безопасная подготовка проекта/площадки к РЕАЛЬНОЙ автопубликации по
календарю. Сервис проверяет готовность (автопилот, календарь, медиа, баланс, площадки,
безопасность), хранит per-project/per-platform переключатели и вычисляет «эффективный live-гейт».

БЕЗОПАСНОСТЬ (инварианты):
- сервис НИКОГДА не включает и не меняет глобальные ``*_LIVE_PUBLISHING_ENABLED`` флаги;
- per-project/per-platform switch НЕ обходит глобальные флаги — они всё равно обязательны;
- включение live требует явного подтверждения (текст) и порога готовности;
- никаких реальных публикаций, внешних probe-вызовов (по умолчанию) и сырых токенов наружу.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import live_readiness_repository as readiness_repo
from app.repositories import project_repository
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

# Глобальные live-флаги по площадкам (админ-управляемые; сервис их только читает).
_GLOBAL_LIVE_FLAG_ATTR: dict[str, str] = {
    "telegram": "telegram_live_publishing_enabled",
    "vk": "vk_live_publishing_enabled",
    "instagram": "instagram_live_publishing_enabled",
}
# Требования площадок (клиентская сторона; секретов не храним — только признак наличия).
_PLATFORM_REQUIRED_FIELDS: dict[str, list[str]] = {
    "telegram": ["connection", "bot_token", "channel_id"],
    "vk": ["connection", "access_token", "group_id"],
    "instagram": ["connection", "access_token", "public_image_url"],
}
_LIVE_CAPABLE = ("telegram", "vk", "instagram")
_COMING_SOON = ("max", "ok")


class LiveReadinessError(Exception):
    """Ошибка live-readiness (нет проекта/доступа/данных/подтверждения) — API → 400/404."""


class LiveReadinessService:
    """Аудит готовности к реальной автопубликации + per-project/per-platform live switch."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Профили                                                            #
    # ------------------------------------------------------------------ #

    def get_or_create_project_profile(
        self, db: Session, project_id: int, current_user_id: int | None = None
    ) -> Any:
        """Получить/создать профиль готовности проекта."""
        project = self._require_project(db, project_id)
        autopilot_profile_id = self._autopilot_profile_id(db, project_id)
        return readiness_repo.get_or_create_project_profile(
            db,
            account_id=project.account_id,
            project_id=project_id,
            autopilot_profile_id=autopilot_profile_id,
        )

    # ------------------------------------------------------------------ #
    # Проверка готовности проекта                                        #
    # ------------------------------------------------------------------ #

    def run_project_readiness_check(
        self,
        db: Session,
        project_id: int,
        current_user_id: int | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Проверить готовность проекта к реальной автопубликации (без публикации)."""
        project = self._require_project(db, project_id)
        settings = self._resolve_settings()
        profile = readiness_repo.get_project_profile(db, project_id)

        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        checklist: dict[str, Any] = {}

        # 1. Автопилот.
        autopilot = self._autopilot_profile(db, project_id)
        has_autopilot = autopilot is not None
        autopilot_running = bool(
            autopilot is not None and (autopilot.is_enabled or autopilot.status == "running")
        )
        checklist["autopilot"] = {
            "done": has_autopilot,
            "running": autopilot_running,
            "label": "Автопилот",
        }
        if not has_autopilot:
            blockers.append(self._blocker("no_autopilot_profile", "setup", "Настройте автопилот."))
        elif not autopilot_running:
            warnings.append(
                self._blocker("autopilot_not_running", "info", "Автопилот ещё не запущен.")
            )

        # 2. Календарь.
        has_calendar = self._has_calendar(db, project_id)
        checklist["calendar"] = {"done": has_calendar, "label": "Календарь"}
        if settings.live_readiness_check_calendar and not has_calendar:
            blockers.append(
                self._blocker("no_calendar", "setup", "Создайте календарь автопостинга.")
            )

        # 3. Яндекс Диск / медиа.
        media_count = self._media_count(db, project_id)
        has_yandex = self._has_yandex(db, project_id)
        checklist["yandex_disk"] = {"done": has_yandex, "label": "Яндекс Диск"}
        if not has_yandex:
            warnings.append(
                self._blocker("no_yandex_disk", "info", "Подключите Яндекс Диск с картинками.")
            )
        min_media = settings.autopilot_min_media_assets_safe
        media_status = {
            "total": media_count,
            "min_recommended": min_media,
            "enough": media_count >= max(1, min_media),
        }
        checklist["media"] = {"done": media_count > 0, "label": "Картинки"}
        if settings.live_readiness_check_media and media_count <= 0:
            blockers.append(self._blocker("no_media", "setup", "Добавьте картинки в медиатеку."))
        elif media_count < min_media:
            warnings.append(
                self._blocker(
                    "weak_media_library",
                    "info",
                    f"Мало картинок ({media_count}). Рекомендуем от {min_media}.",
                )
            )

        # 4. Баланс.
        balance = self._balance_units(db, project.account_id)
        autopost_cost = self._autopost_cost()
        billing_status = {
            "balance_units": balance,
            "cost_per_post": autopost_cost,
            "approx_posts_left": (
                int(balance // autopost_cost) if balance and autopost_cost else 0
            ),
            "enough": bool(balance and balance >= autopost_cost),
        }
        checklist["balance"] = {"done": billing_status["enough"], "label": "Баланс"}
        if project.account_id is None:
            blockers.append(
                self._blocker("no_billing_account", "setup", "Нет платёжного аккаунта.")
            )
        elif settings.live_readiness_check_balance and not billing_status["enough"]:
            blockers.append(
                self._blocker(
                    "insufficient_balance", "blocking", "Недостаточно баланса для публикаций."
                )
            )

        # 5. Расписание.
        has_schedule = self._has_active_publishing_plan(db, project_id)
        schedule_status = {"configured": has_schedule}
        checklist["schedule"] = {"done": has_schedule, "label": "Расписание"}
        if not has_schedule:
            blockers.append(
                self._blocker("schedule_missing", "setup", "Примените календарь к автопилоту.")
            )

        # 6. Площадки (per-platform readiness + глобальные флаги).
        platform_statuses: dict[str, Any] = {}
        selected = self._selected_platforms(db, project_id, autopilot)
        any_global_live = False
        any_platform_ready = False
        for platform in selected:
            pres = self.run_platform_readiness_check(
                db, project_id, platform, current_user_id, dry_run=True
            )
            platform_statuses[platform] = pres
            if pres.get("global_live_enabled"):
                any_global_live = True
            if pres.get("status") == "ready":
                any_platform_ready = True
        checklist["platforms"] = {
            "done": any_platform_ready,
            "label": "Площадки",
            "selected": selected,
        }
        if not selected:
            blockers.append(self._blocker("platform_live_disabled", "setup", "Выберите площадки."))
        elif not any_platform_ready:
            blockers.append(
                self._blocker(
                    "platform_credentials_missing", "setup", "Завершите настройку площадок."
                )
            )
        if selected and not any_global_live:
            warnings.append(
                self._blocker(
                    "global_live_flag_disabled",
                    "info",
                    "Условия публикации выключены администратором — посты пойдут на проверку.",
                )
            )

        # 7. Безопасность.
        project_live_enabled = bool(profile and profile.project_live_enabled)
        full_auto_live_enabled = bool(profile and profile.full_auto_live_enabled)
        security_status = {
            "confirmation_required": settings.live_readiness_require_confirmation_effective,
            "global_live_any": any_global_live,
            "project_live_enabled": project_live_enabled,
            "full_auto_live_enabled": full_auto_live_enabled,
            "global_flag_override_allowed": bool(
                settings.live_readiness_allow_global_flag_override
            ),
        }
        checklist["security"] = {"done": project_live_enabled, "label": "Безопасность"}
        if not project_live_enabled:
            warnings.append(
                self._blocker(
                    "project_live_disabled",
                    "info",
                    "Реальная публикация для проекта ещё не включена.",
                )
            )

        score = self._project_score(checklist)
        status = self._status_from(blockers, score, settings)
        can_enable_live = self._can_enable(blockers, score, settings)
        can_publish_live_now = bool(
            can_enable_live
            and project_live_enabled
            and full_auto_live_enabled
            and any_global_live
            and any_platform_ready
        )
        live_mode = self._live_mode(
            project_live_enabled, full_auto_live_enabled, any_global_live, status
        )

        result = {
            "project_id": project_id,
            "status": status,
            "readiness_score": score,
            "blockers": blockers,
            "warnings": warnings,
            "checklist": checklist,
            "platform_statuses": platform_statuses,
            "billing_status": billing_status,
            "media_status": media_status,
            "schedule_status": schedule_status,
            "security_status": security_status,
            "live_mode": live_mode,
            "can_enable_live": can_enable_live,
            "can_publish_live_now": can_publish_live_now,
            "next_best_action": self._next_action(blockers, project_live_enabled, can_enable_live),
            "dry_run": dry_run,
        }

        if not dry_run and settings.live_readiness_enabled_effective:
            profile = self.get_or_create_project_profile(db, project_id, current_user_id)
            readiness_repo.update_project_check_result(db, profile, result)
            self._write_audit(
                db,
                audit_actions.ACTION_LIVE_READINESS_CHECKED,
                project.account_id,
                project_id,
                {"status": status, "score": score, "blockers": [b["type"] for b in blockers]},
            )
            if settings.live_readiness_notify_on_blockers and blockers:
                self.notify_blockers_if_needed(db, project_id, blockers)
        return result

    # ------------------------------------------------------------------ #
    # Проверка готовности площадки                                       #
    # ------------------------------------------------------------------ #

    def run_platform_readiness_check(
        self,
        db: Session,
        project_id: int,
        platform_key: str,
        current_user_id: int | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Проверить готовность конкретной площадки (без публикации, без внешних probe)."""
        project = self._require_project(db, project_id)
        settings = self._resolve_settings()
        platform_key = str(platform_key or "").strip().lower()
        profile = readiness_repo.get_platform_profile(db, project_id, platform_key)

        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        required = list(_PLATFORM_REQUIRED_FIELDS.get(platform_key, ["connection"]))
        missing: list[str] = []

        # Площадки «скоро».
        if platform_key in _COMING_SOON:
            res = {
                "project_id": project_id,
                "platform_key": platform_key,
                "status": "blocked",
                "readiness_score": 0,
                "supported": False,
                "coming_soon": True,
                "global_live_enabled": False,
                "platform_live_enabled": False,
                "credentials_present": False,
                "required_fields": required,
                "missing_fields": required,
                "blockers": [self._blocker("platform_check_failed", "info", "Площадка скоро.")],
                "warnings": [],
                "capabilities": {},
                "media_requirements": {},
                "dry_run": dry_run,
            }
            self._maybe_persist_platform(db, project, platform_key, res, dry_run, current_user_id)
            return res

        connection = self._connection(db, project_id, platform_key)
        connected = bool(connection and connection.get("connected"))
        creds_present = bool(connection and connection.get("api_key_present"))
        external_id = (connection or {}).get("external_id")
        global_live = self._global_live_enabled(settings, platform_key)

        if not connected:
            missing.append("connection")
            blockers.append(
                self._blocker("platform_credentials_missing", "setup", "Подключите площадку.")
            )
        # Требования по конкретной площадке.
        if platform_key == "telegram":
            if not creds_present:
                missing.append("bot_token")
            if not external_id:
                missing.append("channel_id")
                blockers.append(self._blocker("platform_check_failed", "setup", "Укажите канал."))
        elif platform_key == "vk":
            if not creds_present:
                missing.append("access_token")
            if not external_id:
                missing.append("group_id")
                blockers.append(self._blocker("platform_check_failed", "setup", "Укажите группу."))
            warnings.append(
                self._blocker(
                    "platform_check_failed",
                    "info",
                    "Для фото во VK нужен пользовательский токен (групповой фото не грузит).",
                )
            )
        elif platform_key == "instagram":
            if not creds_present:
                missing.append("access_token")
            if not settings.media_proxy_https_ready:
                missing.append("public_image_url")
                blockers.append(
                    self._blocker(
                        "instagram_public_url_missing",
                        "setup",
                        "Нужен публичный HTTPS-адрес картинок (media proxy).",
                    )
                )
        if creds_present and platform_key in ("telegram", "vk"):
            # токен есть → base connection field закрыт
            missing = [m for m in missing if m != "connection"]

        if not global_live:
            warnings.append(
                self._blocker(
                    "global_live_flag_disabled",
                    "info",
                    "Условия публикации для площадки выключены администратором.",
                )
            )

        missing = sorted(set(missing))
        score = self._platform_score(required, missing, global_live)
        setup_blockers = [b for b in blockers if b["severity"] in ("setup", "blocking")]
        status = "ready" if not setup_blockers else "not_ready"
        platform_live_enabled = bool(profile and profile.platform_live_enabled)

        res = {
            "project_id": project_id,
            "platform_key": platform_key,
            "status": status,
            "readiness_score": score,
            "supported": True,
            "coming_soon": False,
            "connected": connected,
            "credentials_present": creds_present,
            "target_present": bool(external_id),
            "global_live_enabled": global_live,
            "platform_live_enabled": platform_live_enabled,
            "required_fields": required,
            "missing_fields": missing,
            "blockers": blockers,
            "warnings": warnings,
            "capabilities": {"live_capable": platform_key in _LIVE_CAPABLE},
            "media_requirements": {
                "public_image_url_required": platform_key == "instagram",
                "public_image_url_ready": bool(settings.media_proxy_https_ready),
            },
            "confirmation_required": settings.live_readiness_require_platform_confirmation,
            "dry_run": dry_run,
        }
        self._maybe_persist_platform(db, project, platform_key, res, dry_run, current_user_id)
        return res

    def _maybe_persist_platform(
        self,
        db: Session,
        project: Any,
        platform_key: str,
        res: dict[str, Any],
        dry_run: bool,
        current_user_id: int | None,
    ) -> None:
        settings = self._resolve_settings()
        if dry_run or not settings.live_readiness_enabled_effective:
            return
        profile = readiness_repo.get_or_create_platform_profile(
            db, project.account_id, project.id, platform_key, res.get("resource_id")
        )
        readiness_repo.update_platform_check_result(
            db,
            profile,
            {
                "status": res["status"],
                "readiness_score": res["readiness_score"],
                "credentials_present": res.get("credentials_present", False),
                "last_probe_status": "skipped_no_external_probe",
                "blockers": res["blockers"],
                "warnings": res["warnings"],
                "required_fields": res["required_fields"],
                "missing_fields": res["missing_fields"],
                "capabilities": res["capabilities"],
                "media_requirements": res.get("media_requirements", {}),
            },
        )
        self._write_audit(
            db,
            audit_actions.ACTION_LIVE_READINESS_PLATFORM_CHECKED,
            project.account_id,
            project.id,
            {"platform": platform_key, "status": res["status"], "score": res["readiness_score"]},
        )

    # ------------------------------------------------------------------ #
    # Dashboard                                                          #
    # ------------------------------------------------------------------ #

    def build_project_live_dashboard(self, db: Session, project_id: int) -> dict[str, Any]:
        """Клиентский дашборд готовности к реальной автопубликации."""
        self._require_project(db, project_id)
        settings = self._resolve_settings()
        check = self.run_project_readiness_check(db, project_id, dry_run=True)
        status_label = {
            "ready": "Готово",
            "warning": "Почти готово",
            "not_ready": "Нужно исправить",
            "blocked": "Заблокировано",
            "failed": "Ошибка",
            "not_checked": "Проверка не запускалась",
        }.get(check["status"], "Проверка не запускалась")
        return {
            "project_id": project_id,
            "status": check["status"],
            "status_label": status_label,
            "readiness_score": check["readiness_score"],
            "checklist": check["checklist"],
            "blockers": check["blockers"],
            "warnings": check["warnings"],
            "platform_statuses": check["platform_statuses"],
            "billing_status": check["billing_status"],
            "media_status": check["media_status"],
            "schedule_status": check["schedule_status"],
            "security_status": check["security_status"],
            "live_mode": check["live_mode"],
            "can_enable_live": check["can_enable_live"],
            "can_publish_live_now": check["can_publish_live_now"],
            "next_best_action": check["next_best_action"],
            "confirmation": {
                "project_text": settings.live_autopilot_confirmation_text_safe,
                "platform_text": settings.live_platform_confirmation_text_safe,
                "required": settings.live_readiness_require_confirmation_effective,
                "min_score": settings.live_readiness_min_score_to_enable_safe,
            },
            "note": (
                "Это не включает глобальные env-флаги. Реальная публикация сработает только если "
                "условия публикации включены администратором."
            ),
        }

    # ------------------------------------------------------------------ #
    # Включение / выключение live                                        #
    # ------------------------------------------------------------------ #

    def enable_project_live(
        self,
        db: Session,
        project_id: int,
        confirmation: str,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Включить per-project live (подтверждение + порог готовности). Global-флаги не трогает."""
        project = self._require_project(db, project_id)
        settings = self._resolve_settings()
        self._require_confirmation(confirmation, settings.live_autopilot_confirmation_text_safe)
        check = self.run_project_readiness_check(db, project_id, current_user_id, dry_run=False)
        if not check["can_enable_live"]:
            raise LiveReadinessError(
                "Проект ещё не готов к включению: исправьте блокеры или поднимите готовность."
            )
        profile = self.get_or_create_project_profile(db, project_id, current_user_id)
        readiness_repo.set_project_live_enabled(db, profile, True, current_user_id)
        self._write_audit(
            db,
            audit_actions.ACTION_LIVE_READINESS_PROJECT_ENABLED,
            project.account_id,
            project_id,
            {"score": check["readiness_score"]},
        )
        return {
            "ok": True,
            "project_live_enabled": True,
            "global_flags_changed": False,
            "note": (
                "Live для проекта включён. Реальная публикация сработает только при включённых "
                "администратором условиях публикации."
            ),
        }

    def disable_project_live(
        self, db: Session, project_id: int, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """Выключить per-project live (и full-auto). Global-флаги не трогает."""
        project = self._require_project(db, project_id)
        profile = self.get_or_create_project_profile(db, project_id, current_user_id)
        readiness_repo.set_project_live_enabled(db, profile, False, current_user_id)
        self._write_audit(
            db,
            audit_actions.ACTION_LIVE_READINESS_PROJECT_DISABLED,
            project.account_id,
            project_id,
            {},
        )
        return {"ok": True, "project_live_enabled": False, "full_auto_live_enabled": False}

    def enable_platform_live(
        self,
        db: Session,
        project_id: int,
        platform_key: str,
        confirmation: str,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Включить per-platform live (подтверждение + порог). Global-флаги не трогает."""
        project = self._require_project(db, project_id)
        settings = self._resolve_settings()
        platform_key = str(platform_key or "").strip().lower()
        self._require_confirmation(confirmation, settings.live_platform_confirmation_text_safe)
        check = self.run_platform_readiness_check(
            db, project_id, platform_key, current_user_id, dry_run=False
        )
        threshold = settings.live_readiness_min_score_to_enable_safe
        if check["status"] != "ready" or check["readiness_score"] < threshold:
            raise LiveReadinessError("Площадка ещё не готова к включению live.")
        profile = readiness_repo.get_or_create_platform_profile(
            db, project.account_id, project_id, platform_key
        )
        readiness_repo.set_platform_live_enabled(db, profile, True, current_user_id)
        self._write_audit(
            db,
            audit_actions.ACTION_LIVE_READINESS_PLATFORM_ENABLED,
            project.account_id,
            project_id,
            {"platform": platform_key, "score": check["readiness_score"]},
        )
        return {
            "ok": True,
            "platform_key": platform_key,
            "platform_live_enabled": True,
            "global_flags_changed": False,
        }

    def disable_platform_live(
        self,
        db: Session,
        project_id: int,
        platform_key: str,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Выключить per-platform live. Global-флаги не трогает."""
        project = self._require_project(db, project_id)
        platform_key = str(platform_key or "").strip().lower()
        profile = readiness_repo.get_or_create_platform_profile(
            db, project.account_id, project_id, platform_key
        )
        readiness_repo.set_platform_live_enabled(db, profile, False, current_user_id)
        self._write_audit(
            db,
            audit_actions.ACTION_LIVE_READINESS_PLATFORM_DISABLED,
            project.account_id,
            project_id,
            {"platform": platform_key},
        )
        return {"ok": True, "platform_key": platform_key, "platform_live_enabled": False}

    def enable_full_auto_live(
        self,
        db: Session,
        project_id: int,
        confirmation: str,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Включить full-auto live (нужны project_live + готовые площадки + подтверждение)."""
        project = self._require_project(db, project_id)
        settings = self._resolve_settings()
        self._require_confirmation(confirmation, settings.live_autopilot_confirmation_text_safe)
        profile = self.get_or_create_project_profile(db, project_id, current_user_id)
        if not profile.project_live_enabled:
            raise LiveReadinessError("Сначала включите live для проекта.")
        platform_profiles = readiness_repo.list_platform_profiles(db, project_id)
        ready_live = [
            p for p in platform_profiles if p.platform_live_enabled and p.status == "ready"
        ]
        if not ready_live:
            raise LiveReadinessError("Нет ни одной готовой площадки с включённым live.")
        readiness_repo.set_full_auto_live_enabled(db, profile, True, current_user_id)
        self._write_audit(
            db,
            audit_actions.ACTION_LIVE_READINESS_FULL_AUTO_ENABLED,
            project.account_id,
            project_id,
            {"platforms": [p.platform_key for p in ready_live]},
        )
        return {"ok": True, "full_auto_live_enabled": True, "global_flags_changed": False}

    def disable_full_auto_live(
        self, db: Session, project_id: int, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """Выключить full-auto live для проекта."""
        project = self._require_project(db, project_id)
        profile = self.get_or_create_project_profile(db, project_id, current_user_id)
        readiness_repo.set_full_auto_live_enabled(db, profile, False, current_user_id)
        self._write_audit(
            db,
            audit_actions.ACTION_LIVE_READINESS_FULL_AUTO_DISABLED,
            project.account_id,
            project_id,
            {},
        )
        return {"ok": True, "full_auto_live_enabled": False}

    # ------------------------------------------------------------------ #
    # Эффективный live-гейт                                              #
    # ------------------------------------------------------------------ #

    def build_effective_live_gate(
        self, db: Session, project_id: int, platform_key: str
    ) -> dict[str, Any]:
        """Итоговый live-гейт (project × platform). Global-флаги обязательны и не обходятся."""
        settings = self._resolve_settings()
        platform_key = str(platform_key or "").strip().lower()
        project_profile = readiness_repo.get_project_profile(db, project_id)
        platform_profile = readiness_repo.get_platform_profile(db, project_id, platform_key)

        global_live = self._global_live_enabled(settings, platform_key)
        project_live = bool(project_profile and project_profile.project_live_enabled)
        full_auto_live = bool(project_profile and project_profile.full_auto_live_enabled)
        platform_live = bool(platform_profile and platform_profile.platform_live_enabled)
        readiness_ready = bool(
            project_profile
            and project_profile.status == "ready"
            and platform_profile
            and platform_profile.status == "ready"
        )
        can_publish_live = bool(
            global_live and project_live and platform_live and full_auto_live and readiness_ready
        )
        blocked_reasons: list[str] = []
        if not global_live:
            blocked_reasons.append("global_live_flag_disabled")
        if not project_live:
            blocked_reasons.append("project_live_disabled")
        if not platform_live:
            blocked_reasons.append("platform_live_disabled")
        if not full_auto_live:
            blocked_reasons.append("full_auto_live_disabled")
        if not readiness_ready:
            blocked_reasons.append("readiness_not_ready")
        return {
            "project_id": project_id,
            "platform_key": platform_key,
            "global_live_enabled": global_live,
            "project_live_enabled": project_live,
            "platform_live_enabled": platform_live,
            "full_auto_live_enabled": full_auto_live,
            "readiness_ready": readiness_ready,
            "project_profile_exists": project_profile is not None,
            "can_publish_live": can_publish_live,
            "blocked_reasons": blocked_reasons,
        }

    # ------------------------------------------------------------------ #
    # Notifications                                                      #
    # ------------------------------------------------------------------ #

    def notify_blockers_if_needed(
        self, db: Session, project_id: int, blockers: list[dict[str, Any]]
    ) -> None:
        """Уведомить владельца о блокерах готовности (мягко, без внешней доставки)."""
        settings = self._resolve_settings()
        if not settings.live_readiness_notify_on_blockers or not blockers:
            return
        try:
            project = project_repository.get_project_by_id(db, project_id)
            owner_id = self._owner_user_id(db, project)
            if owner_id is None:
                return
            self._notification_service().create_notification(
                db,
                recipient_user_id=owner_id,
                notification_type="live_readiness_blocked",
                title="Готовность к автопубликации: нужно исправить",
                message="Автопилот готовит посты, но реальная публикация ещё не готова.",
                account_id=project.account_id if project else None,
                project_id=project_id,
                priority="normal",
                action_url=f"/ui/projects/{project_id}/live-readiness",
                metadata={"blockers": [b["type"] for b in blockers][:10]},
            )
        except Exception:  # noqa: BLE001 — уведомление не должно ронять основное действие
            logger.warning("live-readiness notify failed for project_id=%s", project_id)

    # ------------------------------------------------------------------ #
    # Внутреннее: сигналы проекта                                        #
    # ------------------------------------------------------------------ #

    def _autopilot_profile(self, db: Session, project_id: int) -> Any:
        try:
            from app.repositories import autopilot_repository

            return autopilot_repository.get_profile_by_project_id(db, project_id)
        except Exception:  # noqa: BLE001
            return None

    def _autopilot_profile_id(self, db: Session, project_id: int) -> int | None:
        profile = self._autopilot_profile(db, project_id)
        return profile.id if profile is not None else None

    def _has_calendar(self, db: Session, project_id: int) -> bool:
        try:
            from app.repositories import autopilot_calendar_repository as calendar_repo

            if calendar_repo.get_active_plan_for_project(db, project_id) is not None:
                return True
        except Exception:  # noqa: BLE001
            pass
        return self._has_active_publishing_plan(db, project_id)

    def _has_active_publishing_plan(self, db: Session, project_id: int) -> bool:
        try:
            from app.repositories import crm_bot_smm_repository as crm_repo

            config = crm_repo.get_config_by_project_id(db, project_id)
            if config is None:
                return False
            return any(p.is_active for p in crm_repo.list_plans_by_config(db, config.id))
        except Exception:  # noqa: BLE001
            return False

    def _has_yandex(self, db: Session, project_id: int) -> bool:
        try:
            from app.repositories import yandex_auto_sync_repository

            if yandex_auto_sync_repository.get_profile_by_project_id(db, project_id) is not None:
                return True
        except Exception:  # noqa: BLE001
            pass
        conn = self._connection(db, project_id, "yandex_disk")
        return bool(conn and conn.get("connected"))

    def _media_count(self, db: Session, project_id: int) -> int:
        try:
            from app.repositories import media_asset_repository

            return int(media_asset_repository.count_media_assets(db, project_id=project_id))
        except Exception:  # noqa: BLE001
            return 0

    def _selected_platforms(self, db: Session, project_id: int, autopilot: Any) -> list[str]:
        plans = self._active_publishing_plans(db, project_id)
        if plans and plans[0].platforms:
            raw = list(plans[0].platforms)
        elif autopilot is not None and autopilot.primary_platforms:
            raw = list(autopilot.primary_platforms)
        else:
            raw = []
        return [str(p).strip().lower() for p in raw if str(p).strip() and p != "yandex_disk"]

    def _active_publishing_plans(self, db: Session, project_id: int) -> list[Any]:
        try:
            from app.repositories import crm_bot_smm_repository as crm_repo

            config = crm_repo.get_config_by_project_id(db, project_id)
            if config is None:
                return []
            return [p for p in crm_repo.list_plans_by_config(db, config.id) if p.is_active]
        except Exception:  # noqa: BLE001
            return []

    def _connection(self, db: Session, project_id: int, platform_key: str) -> dict[str, Any] | None:
        try:
            conn: dict[str, Any] | None = self._platform_service().get_connection(
                db, project_id, platform_key
            )
            return conn
        except Exception:  # noqa: BLE001
            return None

    def _balance_units(self, db: Session, account_id: int | None) -> int | None:
        if account_id is None:
            return None
        try:
            account = self._billing_service().get_balance(db, account_id)
            return int(getattr(account, "balance_units", 0) or 0)
        except Exception:  # noqa: BLE001
            return None

    def _autopost_cost(self) -> int:
        try:
            from app.services.billing_service import USAGE_AUTO_PUBLISH_ACTION

            return int(self._billing_service().estimate_action_cost(USAGE_AUTO_PUBLISH_ACTION))
        except Exception:  # noqa: BLE001
            return 5

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
    # Внутреннее: расчёты                                                #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _global_live_enabled(settings: Any, platform_key: str) -> bool:
        attr = _GLOBAL_LIVE_FLAG_ATTR.get(platform_key)
        return bool(getattr(settings, attr, False)) if attr else False

    @staticmethod
    def _project_score(checklist: dict[str, Any]) -> int:
        weights = {
            "autopilot": 15,
            "calendar": 15,
            "yandex_disk": 10,
            "media": 15,
            "balance": 15,
            "schedule": 10,
            "platforms": 15,
            "security": 5,
        }
        total = sum(weights.values())
        got = sum(w for key, w in weights.items() if checklist.get(key, {}).get("done"))
        return int(round(got * 100 / total)) if total else 0

    @staticmethod
    def _platform_score(required: list[str], missing: list[str], global_live: bool) -> int:
        req = len(required) or 1
        satisfied = max(0, req - len([m for m in missing if m in required]))
        base = int(round(satisfied * 90 / req))
        return min(100, base + (10 if global_live else 0))

    @staticmethod
    def _status_from(blockers: list[dict[str, Any]], score: int, settings: Any) -> str:
        if any(b["severity"] == "blocking" for b in blockers):
            return "blocked"
        if any(b["severity"] == "setup" for b in blockers):
            return "not_ready"
        if score >= settings.live_readiness_min_score_to_enable_safe:
            return "ready"
        return "warning"

    @staticmethod
    def _can_enable(blockers: list[dict[str, Any]], score: int, settings: Any) -> bool:
        if any(b["severity"] in ("blocking", "setup") for b in blockers):
            return False
        threshold = int(settings.live_readiness_min_score_to_enable_safe)
        return score >= threshold

    @staticmethod
    def _live_mode(project_live: bool, full_auto_live: bool, global_live: bool, status: str) -> str:
        if not project_live:
            return "disabled"
        if not global_live:
            return "dry_run_only"
        if full_auto_live and status == "ready":
            return "live_allowed"
        if status == "ready":
            return "full_auto_allowed"
        return "semi_auto_required"

    @staticmethod
    def _next_action(
        blockers: list[dict[str, Any]], project_live: bool, can_enable: bool
    ) -> dict[str, Any]:
        if blockers:
            return {"action": "fix_blockers", "label": "Исправьте, что мешает публикации"}
        if not project_live and can_enable:
            return {"action": "enable_project_live", "label": "Включить реальную публикацию"}
        if project_live:
            return {"action": "open_autopilot", "label": "Открыть автопилот"}
        return {"action": "run_check", "label": "Проверить готовность"}

    # ------------------------------------------------------------------ #
    # Внутреннее: инфраструктура                                         #
    # ------------------------------------------------------------------ #

    def _require_project(self, db: Session, project_id: int) -> Any:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise LiveReadinessError("Проект не найден")
        return project

    @staticmethod
    def _require_confirmation(confirmation: str, expected: str) -> None:
        if str(confirmation or "").strip() != expected:
            raise LiveReadinessError(f"Требуется подтверждение: введите «{expected}»")

    @staticmethod
    def _blocker(blocker_type: str, severity: str, message: str) -> dict[str, Any]:
        return {"type": blocker_type, "severity": severity, "message": message}

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _platform_service(self) -> Any:
        if getattr(self, "_platform_svc", None) is None:
            from app.services.platform_connection_service import get_platform_connection_service

            self._platform_svc = get_platform_connection_service()
        return self._platform_svc

    def _billing_service(self) -> Any:
        if getattr(self, "_billing_svc", None) is None:
            from app.services.billing_service import BillingService

            self._billing_svc = BillingService(settings=self._settings)
        return self._billing_svc

    def _notification_service(self) -> Any:
        if getattr(self, "_notif_svc", None) is None:
            from app.services.notification_service import get_notification_service

            self._notif_svc = get_notification_service()
        return self._notif_svc

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
            entity_type="live_readiness",
            metadata=metadata or {},
        )


def get_live_readiness_service() -> LiveReadinessService:
    """DI-фабрика сервиса live-readiness."""
    return LiveReadinessService()
