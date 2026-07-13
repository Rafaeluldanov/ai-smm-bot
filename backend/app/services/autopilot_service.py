"""Сервис автопилота проекта — v0.5.6.

Продуктовый принцип: Botfleet — автопилот SMM. Клиент подключает площадки, даёт Яндекс Диск,
выбирает календарь и включает автопилот — дальше система сама выбирает тему/CTA/формат/картинки,
пишет текст, адаптирует под площадку и публикует по календарю (если live-gates разрешены; иначе
безопасно создаёт draft/needs_review с понятной причиной). full_auto — основной режим, но он НЕ
включает глобальные live-флаги публикации и НЕ обходит существующие safety-gates.

Сервис — тонкий оркестратор поверх существующих подсистем (platform connections, Яндекс Диск media
source, media quality, schedule automation, billing). Секретов/сырых токенов наружу не отдаёт;
реальных внешних API-вызовов и публикаций не делает; массовую публикацию не запускает.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import (
    autopilot_repository as autopilot_repo,
)
from app.repositories import (
    crm_bot_smm_repository as crm_repo,
)
from app.repositories import (
    media_asset_repository,
    project_repository,
)
from app.schemas.crm_bot_smm import (
    CrmBotProjectConfigCreate,
    CrmPromotionCategoryCreate,
    CrmPublishingPlanCreate,
    CrmPublishingPlanUpdate,
)
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.project_autopilot_profile import ProjectAutopilotProfile
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

# Активные площадки автопилота (соответствуют platform_catalog active).
_AUTOPILOT_PLATFORMS = ("telegram", "vk", "instagram", "website", "odnoklassniki")
# Флаг live-публикации на платформу (по умолчанию все False → посты уходят в needs_review).
_LIVE_FLAG_ATTR = {
    "telegram": "telegram_live_publishing_enabled",
    "vk": "vk_live_publishing_enabled",
    "instagram": "instagram_live_publishing_enabled",
}


class AutopilotError(Exception):
    """Ошибка автопилота (нет проекта/доступа/невалидные данные) — API → 400/404."""


def _now() -> datetime:
    return datetime.now(UTC)


class AutopilotService:
    """Оркестратор автопилота: профиль, health-check, дашборд, конфигурация, старт/пауза."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Профиль                                                            #
    # ------------------------------------------------------------------ #

    def get_or_create_profile(
        self, db: Session, project_id: int, current_user_id: int | None = None
    ) -> ProjectAutopilotProfile:
        """Получить/создать профиль автопилота (mode по умолчанию из конфига)."""
        project = self._require_project(db, project_id)
        created = autopilot_repo.get_profile_by_project_id(db, project_id) is None
        profile = autopilot_repo.get_or_create_profile(
            db,
            account_id=project.account_id,
            project_id=project_id,
            default_mode=self._resolve_settings().autopilot_default_mode_safe,
            current_user_id=current_user_id,
        )
        if created:
            self._write_audit(
                db,
                audit_actions.ACTION_AUTOPILOT_PROFILE_CREATED,
                profile,
                {"mode": profile.mode},
            )
        return profile

    def update_autopilot_mode(
        self, db: Session, project_id: int, mode: str, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """Сменить режим автопилота (full_auto/semi_auto). Live-флаги НЕ трогает."""
        mode = str(mode or "").strip().lower()
        if mode not in ("full_auto", "semi_auto"):
            raise AutopilotError("Режим должен быть full_auto или semi_auto")
        profile = self.get_or_create_profile(db, project_id, current_user_id)
        autopilot_repo.update_profile(
            db, profile, {"mode": mode, "updated_by_user_id": current_user_id}
        )
        self._write_audit(db, audit_actions.ACTION_AUTOPILOT_MODE_CHANGED, profile, {"mode": mode})
        return autopilot_repo.public_profile_view(profile)

    # ------------------------------------------------------------------ #
    # Health check / blockers                                            #
    # ------------------------------------------------------------------ #

    def run_health_check(self, db: Session, project_id: int) -> dict[str, Any]:
        """Проверить готовность автопилота и вернуть статус + блокеры (без побочных эффектов)."""
        project = self._require_project(db, project_id)
        profile = self.get_or_create_profile(db, project_id)
        connections = self._connections(db, project_id)
        connected = [c for c in connections if c.get("connected")]
        media_count = media_asset_repository.count_media_assets(db, project_id=project_id)
        yandex = self._yandex_connection(connections)
        # v0.5.7: Яндекс Диск может быть задан и через профиль авто-синхронизации.
        has_yandex = yandex is not None or self._yandex_sync_has_url(db, project_id)
        plans = self._active_plans(db, project_id)
        balance_units = self._balance_units(db, project.account_id)
        settings = self._resolve_settings()

        blockers: list[dict[str, Any]] = []

        if self._require_platform() and not connected:
            blockers.append(
                self._blocker(
                    "no_platform_connected",
                    "setup",
                    "Подключите хотя бы одну площадку.",
                    "connect_platform",
                )
            )
        else:
            missing_creds = [
                c["platform_key"]
                for c in connected
                if c["platform_key"] != "yandex_disk"
                and not c.get("api_key_present")
                and not c.get("external_id")
            ]
            if missing_creds:
                blockers.append(
                    self._blocker(
                        "platform_credentials_missing",
                        "setup",
                        "Завершите подключение площадки (не хватает доступа).",
                        "connect_platform",
                    )
                )

        if self._require_yandex_disk() and not has_yandex:
            blockers.append(
                self._blocker(
                    "no_yandex_disk",
                    "setup",
                    "Дайте ссылку на Яндекс Диск с картинками.",
                    "connect_media",
                )
            )

        if media_count <= 0:
            blockers.append(
                self._blocker(
                    "no_media",
                    "setup",
                    "В медиатеке пока нет картинок — синхронизируйте Яндекс Диск.",
                    "connect_media",
                )
            )
        elif media_count < settings.autopilot_min_media_assets_safe:
            blockers.append(
                self._blocker(
                    "weak_media_library",
                    "info",
                    f"Мало картинок ({media_count}). Рекомендуем от "
                    f"{settings.autopilot_recommended_media_assets_safe}.",
                    "connect_media",
                )
            )

        if self._require_calendar() and not plans:
            blockers.append(
                self._blocker(
                    "no_calendar",
                    "setup",
                    "Выберите календарь публикаций.",
                    "configure_calendar",
                )
            )

        if balance_units is not None and balance_units <= 0:
            blockers.append(
                self._blocker(
                    "no_balance",
                    "blocking",
                    "Недостаточно баланса для автопостинга.",
                    "open_billing",
                )
            )

        # Instagram: нужен публичный image_url (media proxy готов по HTTPS).
        selected = self._selected_platforms(profile, plans)
        if "instagram" in selected and not settings.media_proxy_https_ready:
            blockers.append(
                self._blocker(
                    "instagram_public_url_missing",
                    "info",
                    "Для Instagram нужен публичный адрес картинок (media proxy).",
                    "fix_blocker",
                )
            )

        # Live-условия: если ни на одну выбранную площадку live не включён — посты уходят в ревью.
        live_platforms = [p for p in selected if self._platform_live_enabled(settings, p)]
        if selected and not live_platforms:
            blockers.append(
                self._blocker(
                    "live_flags_disabled",
                    "info",
                    "Условия публикации выключены: посты будут создаваться на проверку "
                    "(не публикуются автоматически).",
                    "fix_blocker",
                )
            )

        status = self._status_from_blockers(profile, blockers)
        health_status = "ok" if not self._has_setup_or_blocking(blockers) else "attention"
        autopilot_repo.update_profile(
            db,
            profile,
            {
                "active_blockers": blockers,
                "last_health_check_at": _now(),
                "last_health_status": health_status,
                "status": status if not profile.is_enabled else profile.status,
            },
        )
        self._write_audit(
            db,
            audit_actions.ACTION_AUTOPILOT_HEALTH_CHECKED,
            profile,
            {"status": status, "blockers": [b["type"] for b in blockers]},
        )
        return {
            "project_id": project_id,
            "status": status,
            "health_status": health_status,
            "blockers": blockers,
            "next_best_action": self._next_best_action(blockers, profile),
            "connected_platforms": [c["platform_key"] for c in connected],
            "media_count": media_count,
            "has_yandex_disk": yandex is not None,
            "has_calendar": bool(plans),
            "balance_units": balance_units,
            "live_platforms": live_platforms,
        }

    # ------------------------------------------------------------------ #
    # Dashboard / checklist                                              #
    # ------------------------------------------------------------------ #

    def build_autopilot_dashboard(self, db: Session, project_id: int) -> dict[str, Any]:
        """Полный дашборд автопилота проекта (клиентский, без технического жаргона)."""
        self._require_project(db, project_id)
        profile = self.get_or_create_profile(db, project_id)
        health = self.run_health_check(db, project_id)
        connections = self._connections(db, project_id)
        media = self._media_summary(db, project_id)
        plans = self._active_plans(db, project_id)
        balance_units = health["balance_units"]
        settings = self._resolve_settings()
        return {
            "profile": autopilot_repo.public_profile_view(profile),
            "status": health["status"],
            "mode": profile.mode,
            "is_enabled": profile.is_enabled,
            "setup_progress": self.build_setup_checklist(db, project_id),
            "blockers": health["blockers"],
            "next_best_action": health["next_best_action"],
            "connected_platforms": [
                {
                    "platform_key": c["platform_key"],
                    "connected": c.get("connected", False),
                    "status": c.get("status"),
                }
                for c in connections
                if c["platform_key"] != "yandex_disk"
            ],
            "yandex_disk_status": self._yandex_status(connections, db, project_id),
            "media_status": media,
            "calendar_status": self._calendar_status(plans, profile),
            "next_posts": self.preview_next_posts(db, project_id).get("entries", []),
            "today_posts": [],
            "worker_status": {
                "autopilot_enabled": profile.is_enabled,
                "mode": profile.mode,
            },
            "balance_status": self._billing_summary(db, project_id, balance_units),
            "live_gate_status": {
                "live_platforms": health["live_platforms"],
                "auto_publish": bool(health["live_platforms"]),
                "note": (
                    "Публикуем автоматически."
                    if health["live_platforms"]
                    else "Посты создаются на проверку (условия публикации выключены)."
                ),
            },
            "learning_summary": {
                "enabled": True,
                "note": "Бот учится на метриках и улучшает посты.",
            },
            "simple_client_summary": self.summarize_for_client(db, project_id),
            "primary_action": health["next_best_action"],
            "advanced_hidden": not settings.autopilot_show_advanced_settings,
        }

    def build_setup_checklist(self, db: Session, project_id: int) -> dict[str, Any]:
        """Пошаговый чек-лист настройки автопилота (done/pending)."""
        self._require_project(db, project_id)
        profile = autopilot_repo.get_profile_by_project_id(db, project_id)
        connections = self._connections(db, project_id)
        connected = [c for c in connections if c.get("connected")]
        yandex = self._yandex_connection(connections)
        media_count = media_asset_repository.count_media_assets(db, project_id=project_id)
        plans = self._active_plans(db, project_id)
        steps = [
            {"key": "create_project", "title": "Проект создан", "done": True},
            {
                "key": "connect_platform",
                "title": "Площадка подключена",
                "done": bool([c for c in connected if c["platform_key"] != "yandex_disk"]),
            },
            {
                "key": "connect_yandex_disk",
                "title": "Яндекс Диск подключён",
                "done": yandex is not None,
            },
            {"key": "sync_media", "title": "Картинки загружены", "done": media_count > 0},
            {"key": "choose_calendar", "title": "Календарь выбран", "done": bool(plans)},
            {
                "key": "enable_autopilot",
                "title": "Автопилот включён",
                "done": bool(profile and profile.is_enabled),
            },
            {
                "key": "first_post_ready",
                "title": "Первый пост готовится",
                "done": bool(profile and profile.status == "running"),
            },
        ]
        done = sum(1 for s in steps if s["done"])
        return {"steps": steps, "done": done, "total": len(steps)}

    # ------------------------------------------------------------------ #
    # Конфигурация (клиентские мастера)                                  #
    # ------------------------------------------------------------------ #

    def configure_calendar(
        self,
        db: Session,
        project_id: int,
        payload: dict[str, Any],
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Настроить календарь: создать/обновить CrmPublishingPlan + упрощённые calendar_rules."""
        project = self._require_project(db, project_id)
        profile = self.get_or_create_profile(db, project_id, current_user_id)
        settings = self._resolve_settings()

        platforms = [str(p).strip() for p in (payload.get("platforms") or []) if str(p).strip()]
        frequency = str(payload.get("frequency") or "daily").strip()
        weekdays = self._weekdays_for(frequency, payload.get("weekdays"))
        publish_times = [
            str(t).strip() for t in (payload.get("publish_times") or []) if str(t).strip()
        ] or [settings.autopilot_default_publish_time_safe]
        posts_per_day = max(1, min(10, int(payload.get("posts_per_day") or 1)))
        timezone = str(payload.get("timezone") or settings.autopilot_default_timezone_safe).strip()
        start_date = payload.get("start_date")
        end_date = payload.get("end_date")

        config = self._get_or_create_config(db, project)
        category = self._get_or_create_category(db, project, config)
        plan_mode = "auto_schedule" if profile.mode == "full_auto" else "semi_auto"

        existing = crm_repo.list_plans_by_config(db, config.id)
        if existing:
            plan = crm_repo.update_plan(
                db,
                existing[0],
                CrmPublishingPlanUpdate(
                    weekdays=weekdays,
                    posts_per_day=posts_per_day,
                    publish_times=publish_times,
                    platforms=platforms,
                    mode=plan_mode,
                    start_date=start_date,
                    end_date=end_date,
                    timezone=timezone,
                    is_active=True,
                ),
            )
        else:
            plan = crm_repo.create_plan(
                db,
                CrmPublishingPlanCreate(
                    project_id=project_id,
                    config_id=config.id,
                    category_id=category.id,
                    weekdays=weekdays,
                    posts_per_day=posts_per_day,
                    publish_times=publish_times,
                    platforms=platforms,
                    mode=plan_mode,
                    start_date=start_date,
                    end_date=end_date,
                    timezone=timezone,
                    is_active=True,
                ),
            )
        calendar_rules = {
            "frequency": frequency,
            "weekdays": weekdays,
            "publish_times": publish_times,
            "posts_per_day": posts_per_day,
            "platforms": platforms,
            "timezone": timezone,
            "plan_id": plan.id,
        }
        autopilot_repo.update_profile(
            db,
            profile,
            {
                "calendar_rules": calendar_rules,
                "primary_platforms": platforms,
                "updated_by_user_id": current_user_id,
            },
        )
        self._write_audit(
            db,
            audit_actions.ACTION_AUTOPILOT_CALENDAR_CONFIGURED,
            profile,
            {"plan_id": plan.id, "frequency": frequency, "platforms": platforms},
        )
        return {"ok": True, "plan_id": plan.id, "calendar_rules": calendar_rules}

    def configure_yandex_disk(
        self,
        db: Session,
        project_id: int,
        payload: dict[str, Any],
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Подключить Яндекс Диск (media source). Секретов не хранит; сохраняет resource_id."""
        self._require_project(db, project_id)
        profile = self.get_or_create_profile(db, project_id, current_user_id)
        public_url = str(payload.get("public_url") or "").strip()
        if not public_url:
            raise AutopilotError("Укажите публичную ссылку на Яндекс Диск")
        root_folder = str(payload.get("root_folder") or "SMM").strip() or "SMM"
        tags = [str(t).strip() for t in (payload.get("tags") or []) if str(t).strip()]
        connection = self._platform_service().upsert_connection(
            db,
            project_id,
            "yandex_disk",
            {"url": public_url, "root_folder": root_folder, "tags": tags},
        )
        resource_id = connection.get("id")
        autopilot_repo.update_profile(
            db,
            profile,
            {"yandex_resource_id": resource_id, "updated_by_user_id": current_user_id},
        )
        self._write_audit(
            db,
            audit_actions.ACTION_AUTOPILOT_YANDEX_DISK_CONFIGURED,
            profile,
            {"resource_id": resource_id, "root_folder": root_folder},
        )
        return {
            "ok": True,
            "resource_id": resource_id,
            "root_folder": connection.get("root_folder"),
            "public_media_url": connection.get("public_media_url"),
        }

    def configure_content_rules(
        self,
        db: Session,
        project_id: int,
        payload: dict[str, Any],
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Настроить правила контента (цель/тон/глубина/CTA). Внешний AI не вызывается."""
        profile = self.get_or_create_profile(db, project_id, current_user_id)
        rules = {
            "business_goal": str(payload.get("business_goal") or "").strip(),
            "tone": str(payload.get("tone") or "").strip(),
            "post_depth": str(payload.get("post_depth") or "normal").strip(),
            "cta": str(payload.get("cta") or "").strip()[:200],
            "forbidden_phrases": [
                str(p).strip() for p in (payload.get("forbidden_phrases") or []) if str(p).strip()
            ][:50],
            "preferred_topics": [
                str(t).strip() for t in (payload.get("preferred_topics") or []) if str(t).strip()
            ][:50],
        }
        autopilot_repo.update_content_rules(db, profile, rules)
        autopilot_repo.update_profile(db, profile, {"updated_by_user_id": current_user_id})
        self._write_audit(
            db,
            audit_actions.ACTION_AUTOPILOT_CONTENT_RULES_CONFIGURED,
            profile,
            {"business_goal": rules["business_goal"], "tone": rules["tone"]},
        )
        return {"ok": True, "content_rules": rules}

    # ------------------------------------------------------------------ #
    # Старт / пауза                                                      #
    # ------------------------------------------------------------------ #

    def start_autopilot(
        self, db: Session, project_id: int, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """Запустить автопилот. Блокируется при setup/blocking-блокерах. Live-флаги НЕ включает."""
        profile = self.get_or_create_profile(db, project_id, current_user_id)
        health = self.run_health_check(db, project_id)
        blocking = [b for b in health["blockers"] if b["severity"] in ("setup", "blocking")]
        if blocking:
            autopilot_repo.update_profile(
                db,
                profile,
                {
                    "is_enabled": False,
                    "status": "blocked"
                    if any(b["severity"] == "blocking" for b in blocking)
                    else "setup_required",
                },
            )
            self._write_audit(
                db,
                audit_actions.ACTION_AUTOPILOT_BLOCKED,
                profile,
                {"blockers": [b["type"] for b in blocking]},
            )
            return {
                "ok": False,
                "status": profile.status,
                "blockers": blocking,
                "message": "Сначала нужно завершить настройку.",
            }
        autopilot_repo.update_profile(
            db,
            profile,
            {
                "is_enabled": True,
                "status": "running",
                "last_autopilot_run_at": _now(),
                "updated_by_user_id": current_user_id,
            },
        )
        self._write_audit(
            db, audit_actions.ACTION_AUTOPILOT_STARTED, profile, {"mode": profile.mode}
        )
        return {
            "ok": True,
            "status": "running",
            "message": "Автопилот запущен. Botfleet сам пишет и публикует по календарю.",
            "auto_publish": bool(health["live_platforms"]),
        }

    def pause_autopilot(
        self, db: Session, project_id: int, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """Поставить автопилот на паузу."""
        profile = self.get_or_create_profile(db, project_id, current_user_id)
        autopilot_repo.update_profile(
            db,
            profile,
            {"is_enabled": False, "status": "paused", "updated_by_user_id": current_user_id},
        )
        self._write_audit(db, audit_actions.ACTION_AUTOPILOT_PAUSED, profile, {})
        return {"ok": True, "status": "paused", "message": "Автопилот на паузе."}

    # ------------------------------------------------------------------ #
    # Превью / первый пост                                               #
    # ------------------------------------------------------------------ #

    def preview_next_posts(self, db: Session, project_id: int, days: int = 7) -> dict[str, Any]:
        """Превью ближайших публикаций (без записи в БД, без live)."""
        project = self._require_project(db, project_id)
        try:
            preview = self._schedule_service().preview_due_runs(
                db, account_id=project.account_id, project_id=project_id
            )
        except Exception:  # noqa: BLE001 — превью не критично для дашборда
            logger.warning("autopilot preview failed for project_id=%s", project_id)
            return {"entries": [], "due_count": 0, "live_calls": False}
        entries = [
            {
                "platform_key": e.get("platform_key"),
                "run_date": e.get("run_date"),
                "planned_time": e.get("planned_time"),
                "media_count": e.get("media_count"),
                "outcome": e.get("outcome"),
                "would_create_draft": e.get("would_create_draft"),
            }
            for e in (preview.get("entries") or [])
        ]
        return {
            "entries": entries,
            "due_count": preview.get("due_count", 0),
            "live_calls": False,
        }

    def create_first_draft_now(
        self,
        db: Session,
        project_id: int,
        platform_key: str | None = None,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Создать первый пост как draft/needs_review (для онбординга). Без live-публикации."""
        project = self._require_project(db, project_id)
        profile = self.get_or_create_profile(db, project_id, current_user_id)
        try:
            result = self._schedule_service().run_due(
                db,
                account_id=project.account_id,
                project_id=project_id,
                platform_key=platform_key,
            )
        except Exception as exc:  # noqa: BLE001 — единый безопасный маппинг
            raise AutopilotError(f"Не удалось подготовить пост: {exc}") from exc
        self._write_audit(
            db,
            audit_actions.ACTION_AUTOPILOT_FIRST_DRAFT_CREATED,
            profile,
            {"created": result.get("created", 0)},
        )
        return {
            "ok": True,
            "created": result.get("created", 0),
            "status": "needs_review",
            "live_calls": False,
            "note": "Пост создан на проверку (needs_review). Автоматической публикации нет.",
        }

    # ------------------------------------------------------------------ #
    # Клиентская сводка / оценки                                         #
    # ------------------------------------------------------------------ #

    def summarize_for_client(self, db: Session, project_id: int) -> dict[str, Any]:
        """Одна простая сводка: работает / нужна настройка / есть проблема / на паузе."""
        profile = self.get_or_create_profile(db, project_id)
        blockers = list(profile.active_blockers or [])
        has_blocking = any(b.get("severity") == "blocking" for b in blockers)
        has_setup = any(b.get("severity") == "setup" for b in blockers)
        if profile.status == "paused":
            headline, tone = "На паузе", "paused"
        elif has_setup or profile.status == "setup_required":
            headline, tone = "Нужно настроить", "setup"
        elif has_blocking:
            headline, tone = "Есть проблема", "problem"
        elif profile.is_enabled and profile.status == "running":
            headline, tone = "Автопилот работает", "running"
        else:
            headline, tone = "Готов к запуску", "ready"
        return {"headline": headline, "tone": tone, "mode": profile.mode}

    def estimate_posts_left(self, db: Session, project_id: int) -> dict[str, Any]:
        """Оценка, на сколько постов хватит баланса."""
        project = self._require_project(db, project_id)
        balance = self._balance_units(db, project.account_id)
        cost = self._autopost_cost()
        approx = None
        if balance is not None and cost > 0:
            approx = int(balance // cost)
        return {
            "balance_units": balance,
            "cost_per_post": cost,
            "approx_posts_left": approx,
        }

    # ------------------------------------------------------------------ #
    # Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    def _require_project(self, db: Session, project_id: int) -> Any:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise AutopilotError("Проект не найден")
        return project

    def _connections(self, db: Session, project_id: int) -> list[dict[str, Any]]:
        try:
            rows: list[dict[str, Any]] = self._platform_service().list_connections(db, project_id)
            return rows
        except Exception:  # noqa: BLE001 — отсутствие подключений не критично
            return []

    @staticmethod
    def _yandex_connection(connections: list[dict[str, Any]]) -> dict[str, Any] | None:
        for c in connections:
            if c.get("platform_key") == "yandex_disk" and (
                c.get("public_media_url") or c.get("url")
            ):
                return c
        return None

    def _yandex_status(
        self,
        connections: list[dict[str, Any]],
        db: Session | None = None,
        project_id: int | None = None,
    ) -> dict[str, Any]:
        yandex = self._yandex_connection(connections)
        if yandex is not None:
            return {
                "connected": True,
                "root_folder": yandex.get("root_folder"),
                "has_public_url": bool(yandex.get("public_media_url") or yandex.get("url")),
            }
        # v0.5.7: fallback на профиль авто-синхронизации Яндекс Диска.
        if db is not None and project_id is not None:
            sync = self._yandex_sync_profile(db, project_id)
            if sync is not None and (sync.public_url or "").strip():
                return {
                    "connected": True,
                    "root_folder": sync.root_folder,
                    "has_public_url": True,
                    "auto_sync": True,
                }
        return {"connected": False}

    @staticmethod
    def _yandex_sync_profile(db: Session, project_id: int) -> Any:
        try:
            from app.repositories import yandex_auto_sync_repository

            return yandex_auto_sync_repository.get_profile_by_project_id(db, project_id)
        except Exception:  # noqa: BLE001 — отсутствие профиля синхронизации не критично
            return None

    def _yandex_sync_has_url(self, db: Session, project_id: int) -> bool:
        sync = self._yandex_sync_profile(db, project_id)
        return bool(sync is not None and (sync.public_url or "").strip())

    def _media_summary(self, db: Session, project_id: int) -> dict[str, Any]:
        count = media_asset_repository.count_media_assets(db, project_id=project_id)
        summary: dict[str, Any] = {"total": count, "min_required": 0, "quality": None}
        settings = self._resolve_settings()
        summary["min_required"] = settings.autopilot_min_media_assets_safe
        summary["recommended"] = settings.autopilot_recommended_media_assets_safe
        try:
            dashboard = self._quality_service().build_media_quality_dashboard(db, project_id)
            summary["quality"] = {
                "good": dashboard.get("good", 0),
                "excellent": dashboard.get("excellent", 0),
                "weak": dashboard.get("weak", 0),
            }
        except Exception:  # noqa: BLE001 — качество не критично для дашборда
            summary["quality"] = None
        return summary

    def _active_plans(self, db: Session, project_id: int) -> list[Any]:
        config = crm_repo.get_config_by_project_id(db, project_id)
        if config is None:
            return []
        return [p for p in crm_repo.list_plans_by_config(db, config.id) if p.is_active]

    def _calendar_status(self, plans: list[Any], profile: Any) -> dict[str, Any]:
        if not plans:
            return {"configured": False}
        plan = plans[0]
        return {
            "configured": True,
            "frequency": (profile.calendar_rules or {}).get("frequency"),
            "weekdays": list(plan.weekdays or []),
            "publish_times": list(plan.publish_times or []),
            "platforms": list(plan.platforms or []),
            "timezone": plan.timezone,
        }

    def _selected_platforms(self, profile: Any, plans: list[Any]) -> list[str]:
        if plans and plans[0].platforms:
            return list(plans[0].platforms)
        return list(profile.primary_platforms or [])

    @staticmethod
    def _platform_live_enabled(settings: Any, platform: str) -> bool:
        attr = _LIVE_FLAG_ATTR.get(platform)
        return bool(getattr(settings, attr, False)) if attr else False

    def _billing_summary(
        self, db: Session, project_id: int, balance_units: int | None
    ) -> dict[str, Any]:
        estimate = self.estimate_posts_left(db, project_id)
        return {
            "balance_units": balance_units,
            "approx_posts_left": estimate["approx_posts_left"],
            "cost_per_post": estimate["cost_per_post"],
            "learning_included": True,
        }

    def _balance_units(self, db: Session, account_id: int | None) -> int | None:
        if account_id is None:
            return None
        try:
            account = self._billing_service().get_balance(db, account_id)
            return int(getattr(account, "balance_units", 0) or 0)
        except Exception:  # noqa: BLE001 — баланс не критичен для дашборда
            return None

    def _autopost_cost(self) -> int:
        try:
            from app.services.billing_service import USAGE_AUTO_PUBLISH_ACTION

            return int(self._billing_service().estimate_action_cost(USAGE_AUTO_PUBLISH_ACTION))
        except Exception:  # noqa: BLE001
            return 5

    @staticmethod
    def _weekdays_for(frequency: str, explicit: Any) -> list[int]:
        if frequency == "custom" and explicit:
            return sorted({int(d) for d in explicit if 0 <= int(d) <= 6})
        return {
            "daily": [0, 1, 2, 3, 4, 5, 6],
            "weekdays": [0, 1, 2, 3, 4],
            "three_per_week": [0, 2, 4],
        }.get(frequency, [0, 1, 2, 3, 4, 5, 6])

    def _get_or_create_config(self, db: Session, project: Any) -> Any:
        config = crm_repo.get_config_by_project_id(db, project.id)
        if config is not None:
            return config
        return crm_repo.create_config(
            db,
            CrmBotProjectConfigCreate(
                project_id=project.id,
                display_name=project.name or f"Проект {project.id}",
                status="draft",
            ),
        )

    def _get_or_create_category(self, db: Session, project: Any, config: Any) -> Any:
        categories = crm_repo.list_categories_by_config(db, config.id)
        if categories:
            return categories[0]
        return crm_repo.create_category(
            db,
            CrmPromotionCategoryCreate(
                project_id=project.id,
                config_id=config.id,
                title="Автопилот",
                description="Категория автопилота (создана автоматически).",
            ),
        )

    def _status_from_blockers(self, profile: Any, blockers: list[dict[str, Any]]) -> str:
        if profile.status == "paused" and not profile.is_enabled:
            return "paused"
        # Незавершённая настройка приоритетнее балансовых блокеров: сначала клиент настраивает.
        if any(b["severity"] == "setup" for b in blockers):
            return "setup_required"
        if any(b["severity"] == "blocking" for b in blockers):
            return "blocked"
        if profile.is_enabled:
            return "running"
        return "ready"

    @staticmethod
    def _has_setup_or_blocking(blockers: list[dict[str, Any]]) -> bool:
        return any(b["severity"] in ("setup", "blocking") for b in blockers)

    def _next_best_action(self, blockers: list[dict[str, Any]], profile: Any) -> dict[str, Any]:
        priority = ("setup", "blocking", "info")
        for severity in priority:
            for b in blockers:
                if b["severity"] == severity:
                    return {"action": b["action"], "label": b["message"], "blocker": b["type"]}
        if not profile.is_enabled:
            return {"action": "start_autopilot", "label": "Запустить автопилот", "blocker": None}
        return {"action": "open_calendar", "label": "Открыть календарь", "blocker": None}

    @staticmethod
    def _blocker(blocker_type: str, severity: str, message: str, action: str) -> dict[str, Any]:
        return {"type": blocker_type, "severity": severity, "message": message, "action": action}

    def _require_platform(self) -> bool:
        return bool(self._resolve_settings().autopilot_require_platform)

    def _require_yandex_disk(self) -> bool:
        return bool(self._resolve_settings().autopilot_require_yandex_disk)

    def _require_calendar(self) -> bool:
        return bool(self._resolve_settings().autopilot_require_calendar)

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

    def _schedule_service(self) -> Any:
        if getattr(self, "_schedule_svc", None) is None:
            from app.services.schedule_automation_service import (
                get_schedule_automation_service,
            )

            self._schedule_svc = get_schedule_automation_service()
        return self._schedule_svc

    def _quality_service(self) -> Any:
        if getattr(self, "_quality_svc", None) is None:
            from app.services.media_quality_service import get_media_quality_service

            self._quality_svc = get_media_quality_service()
        return self._quality_svc

    def _billing_service(self) -> Any:
        if getattr(self, "_billing_svc", None) is None:
            from app.services.billing_service import BillingService

            self._billing_svc = BillingService()
        return self._billing_svc

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
            entity_type="autopilot_profile",
            entity_id=profile.id,
            metadata=metadata or {},
        )


def get_autopilot_service() -> AutopilotService:
    """DI-фабрика сервиса автопилота."""
    return AutopilotService()
