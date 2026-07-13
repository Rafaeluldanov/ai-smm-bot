"""Сервис Calendar Assistant автопилота — v0.5.8.

Клиент выбирает цель и частоту — Botfleet строит календарь автопостинга: распределяет дни/время,
учитывает площадки, количество медиа, баланс и лучшие часы обучения (если есть). Календарь
сохраняется как ``AutopilotCalendarPlan`` (понятный клиентский слой) и по применению создаёт/
обновляет ``CrmPublishingPlan``.

БЕЗОПАСНОСТЬ:
- построение/применение календаря НЕ публикует и НЕ включает глобальные live-флаги;
- реальная публикация по-прежнему проходит существующие safety-gates;
- секретов/сырых токенов наружу нет; внешних API-вызовов и publish_due нет.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.models.autopilot_calendar_plan import (
    AUTOPILOT_CALENDAR_GOALS,
    AUTOPILOT_CALENDAR_PRESETS,
    CALENDAR_PRESET_DEFS,
)
from app.repositories import (
    autopilot_calendar_repository as calendar_repo,
)
from app.repositories import (
    media_asset_repository,
    project_repository,
)
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.autopilot_calendar_plan import AutopilotCalendarPlan
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

_WEEKS_PER_MONTH = 4.33
_WEEKDAY_LABELS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
# Цель влияет на рекомендацию частоты/тона (в MVP — на подсказку и confidence).
_GOAL_HINTS: dict[str, str] = {
    "sales": "продажи",
    "leads": "заявки",
    "reach": "охваты",
    "trust": "доверие",
    "expertise": "экспертность",
    "mixed": "смешанная цель",
}


class CalendarAssistantError(Exception):
    """Ошибка Calendar Assistant (нет проекта/доступа/невалидные данные) — API → 400/404."""


class AutopilotCalendarAssistantService:
    """Строит клиентский календарь автопостинга и применяет его к проекту (без публикации)."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Пресеты                                                            #
    # ------------------------------------------------------------------ #

    def build_calendar_presets(self, db: Session, project_id: int) -> list[dict[str, Any]]:
        """Список простых вариантов календаря с оценками постов/месяц и предупреждениями."""
        self._require_project(db, project_id)
        media_count = media_asset_repository.count_media_assets(db, project_id=project_id)
        out: list[dict[str, Any]] = []
        for key in AUTOPILOT_CALENDAR_PRESETS:
            spec = CALENDAR_PRESET_DEFS[key]
            posts_month = self._posts_per_month(spec["weekdays"], spec["posts_per_day"])
            warnings: list[str] = []
            if media_count and media_count < posts_month:
                warnings.append(
                    f"Картинок ({media_count}) может не хватить на {posts_month} постов в месяц."
                )
            out.append(
                {
                    "preset": key,
                    "label": spec["label"],
                    "description": spec["description"],
                    "weekdays": list(spec["weekdays"]),
                    "publish_times": list(spec["publish_times"]),
                    "posts_per_day": spec["posts_per_day"],
                    "estimated_posts_per_month": posts_month,
                    "best_for": spec["best_for"],
                    "warnings": warnings,
                }
            )
        return out

    # ------------------------------------------------------------------ #
    # Preview / recommend                                                #
    # ------------------------------------------------------------------ #

    def preview_calendar(
        self,
        db: Session,
        project_id: int,
        payload: dict[str, Any],
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Построить предпросмотр календаря + риски + оценки. Без записи."""
        project = self._require_project(db, project_id)
        built = self._build_calendar(db, project_id, payload)
        risks = self._compute_risks(db, project_id, built)
        estimates = self._estimate(db, project.account_id, built)
        self._write_audit(
            db,
            audit_actions.ACTION_AUTOPILOT_CALENDAR_PREVIEWED,
            project.account_id,
            project_id,
            {"preset": built["preset"], "goal": built["goal"]},
        )
        return {
            "project_id": project_id,
            "preset": built["preset"],
            "goal": built["goal"],
            "platforms": built["platforms"],
            "weekdays": built["weekdays"],
            "weekday_labels": [_WEEKDAY_LABELS[d] for d in built["weekdays"] if 0 <= d <= 6],
            "publish_times": built["publish_times"],
            "posts_per_day": built["posts_per_day"],
            "timezone": built["timezone"],
            "time_strategy": built["time_strategy"],
            "generated_rules": built["generated_rules"],
            "source_signals": built["source_signals"],
            "risk_flags": [r["type"] for r in risks],
            "risks": risks,
            "estimates": estimates,
            "upcoming_dates": self._upcoming_dates(built["weekdays"], built["publish_times"]),
            "writes": False,
            "note": (
                "Botfleet сам будет писать текст, выбирать картинки и публиковать по этому "
                "календарю. Реальная публикация всё равно проходит условия безопасности."
            ),
        }

    def recommend_calendar(self, db: Session, project_id: int) -> dict[str, Any]:
        """Рекомендовать пресет по медиа/площадкам/балансу/цели."""
        project = self._require_project(db, project_id)
        media_count = media_asset_repository.count_media_assets(db, project_id=project_id)
        platforms = self._project_platforms(db, project_id)
        balance = self._balance_units(db, project.account_id)
        settings = self._resolve_settings()
        goal = settings.autopilot_calendar_default_goal_safe

        # Меньше медиа/баланса → реже; наличие данных обучения повышает уверенность.
        if media_count <= 0 or not platforms:
            preset, reason = (
                "two_per_week",
                "Начните мягко: подключите площадки и добавьте картинки.",
            )
        elif media_count < 8:
            preset, reason = "two_per_week", "Пока мало картинок — рекомендуем 2 раза в неделю."
        elif media_count < 20:
            preset, reason = "three_per_week", "Сбалансированный ритм под ваш объём картинок."
        elif balance is not None and balance < 50:
            preset, reason = "three_per_week", "Хороший ритм с учётом текущего баланса."
        else:
            preset, reason = "weekdays", "Картинок достаточно — можно публиковать по будням."

        best_times = self._learning_best_times(db, project_id)
        confidence = 0.75 if best_times else 0.5
        self._write_audit(
            db,
            audit_actions.ACTION_AUTOPILOT_CALENDAR_RECOMMENDED,
            project.account_id,
            project_id,
            {"preset": preset, "goal": goal},
        )
        return {
            "recommended_preset": preset,
            "goal": goal,
            "reason": reason,
            "confidence_score": confidence,
            "has_learning_data": bool(best_times),
            "best_times": best_times,
        }

    # ------------------------------------------------------------------ #
    # Create / apply                                                     #
    # ------------------------------------------------------------------ #

    def create_calendar_plan(
        self,
        db: Session,
        project_id: int,
        payload: dict[str, Any],
        current_user_id: int | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Создать AutopilotCalendarPlan (dry-run → превью без записи). Не публикует."""
        project = self._require_project(db, project_id)
        built = self._build_calendar(db, project_id, payload)
        risks = self._compute_risks(db, project_id, built)
        estimates = self._estimate(db, project.account_id, built)
        if dry_run:
            preview = self.preview_calendar(db, project_id, payload, current_user_id)
            preview["dry_run"] = True
            return preview
        autopilot_profile_id = self._autopilot_profile_id(db, project_id)
        plan = calendar_repo.create_plan(
            db,
            account_id=project.account_id,
            project_id=project_id,
            autopilot_profile_id=autopilot_profile_id,
            status="draft",
            preset=built["preset"],
            goal=built["goal"],
            platforms=built["platforms"],
            weekdays=built["weekdays"],
            publish_times=built["publish_times"],
            posts_per_day=built["posts_per_day"],
            timezone=built["timezone"],
            start_date=built["start_date"],
            end_date=built["end_date"],
            time_strategy=built["time_strategy"],
            generated_rules=built["generated_rules"],
            source_signals=built["source_signals"],
            risk_flags=[r["type"] for r in risks],
            estimated_posts_per_month=estimates["estimated_posts_per_month"],
            estimated_units_per_month=estimates["estimated_units_per_month"],
            estimated_media_needed=estimates["estimated_media_needed"],
            confidence_score=built["confidence_score"],
            created_by_user_id=current_user_id,
            updated_by_user_id=current_user_id,
        )
        self._write_audit(
            db,
            audit_actions.ACTION_AUTOPILOT_CALENDAR_CREATED,
            project.account_id,
            project_id,
            {"calendar_plan_id": plan.id, "preset": plan.preset},
        )
        return {"ok": True, "dry_run": False, **calendar_repo.public_plan_view(plan)}

    def apply_calendar_to_project(
        self,
        db: Session,
        project_id: int,
        calendar_plan_id: int,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Применить календарь: создать/обновить CrmPublishingPlan автопилота. Без публикации."""
        project = self._require_project(db, project_id)
        settings = self._resolve_settings()
        if not settings.autopilot_calendar_auto_apply_enabled_effective:
            raise CalendarAssistantError("Применение календаря выключено (auto apply disabled)")
        plan = calendar_repo.get_plan_by_id(db, calendar_plan_id)
        if plan is None or plan.project_id != project_id:
            raise CalendarAssistantError("Календарь не найден")
        # Делегируем создание CrmPublishingPlan автопилоту (frequency=custom → точные weekdays).
        result = self._autopilot_service().configure_calendar(
            db,
            project_id,
            {
                "platforms": list(plan.platforms or []),
                "frequency": "custom",
                "weekdays": list(plan.weekdays or []),
                "publish_times": list(plan.publish_times or []),
                "posts_per_day": plan.posts_per_day,
                "timezone": plan.timezone,
                "start_date": plan.start_date,
                "end_date": plan.end_date,
            },
            current_user_id=current_user_id,
        )
        publishing_plan_id = result.get("plan_id")
        linked = list(plan.linked_publishing_plan_ids or [])
        if publishing_plan_id and publishing_plan_id not in linked:
            linked.append(publishing_plan_id)
        calendar_repo.set_linked_publishing_plans(db, plan, linked)
        calendar_repo.activate_plan(db, plan)
        calendar_repo.update_plan(db, plan, {"updated_by_user_id": current_user_id})
        self._write_audit(
            db,
            audit_actions.ACTION_AUTOPILOT_CALENDAR_APPLIED,
            project.account_id,
            project_id,
            {"calendar_plan_id": plan.id, "publishing_plan_id": publishing_plan_id},
        )
        return {
            "ok": True,
            "calendar_plan_id": plan.id,
            "publishing_plan_id": publishing_plan_id,
            "status": "active",
            "live_publish": False,
            "note": (
                "Календарь применён. Автоматической публикации нет — работают условия безопасности."
            ),
        }

    # ------------------------------------------------------------------ #
    # Dashboard / pause / resume / archive                               #
    # ------------------------------------------------------------------ #

    def build_calendar_dashboard(self, db: Session, project_id: int) -> dict[str, Any]:
        """Дашборд календаря: активный план, риски, ближайшие даты, следующий шаг, сводка."""
        self._require_project(db, project_id)
        active = calendar_repo.get_active_plan_for_project(db, project_id)
        plans = calendar_repo.list_plans_for_project(db, project_id, limit=10)
        upcoming: list[dict[str, Any]] = []
        risks: list[str] = []
        if active is not None:
            upcoming = self._upcoming_dates(
                list(active.weekdays or []), list(active.publish_times or [])
            )
            risks = list(active.risk_flags or [])
        return {
            "project_id": project_id,
            "active_plan": calendar_repo.public_plan_view(active) if active else None,
            "has_active_plan": active is not None,
            "plans": [calendar_repo.public_plan_view(p) for p in plans],
            "upcoming_dates": upcoming,
            "risks": risks,
            "next_best_action": self._next_best_action(db, project_id, active),
            "simple_client_summary": self._client_summary(active),
            "presets": self.build_calendar_presets(db, project_id),
        }

    def pause_calendar(
        self, db: Session, project_id: int, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """Поставить активный календарь на паузу (без удаления)."""
        project = self._require_project(db, project_id)
        active = calendar_repo.get_active_plan_for_project(db, project_id)
        if active is None:
            raise CalendarAssistantError("Активный календарь не найден")
        calendar_repo.pause_plan(db, active)
        self._write_audit(
            db,
            audit_actions.ACTION_AUTOPILOT_CALENDAR_PAUSED,
            project.account_id,
            project_id,
            {"calendar_plan_id": active.id},
        )
        return {"ok": True, "status": "paused"}

    def resume_calendar(
        self, db: Session, project_id: int, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """Возобновить последний приостановленный календарь."""
        project = self._require_project(db, project_id)
        paused = next(
            (
                p
                for p in calendar_repo.list_plans_for_project(db, project_id)
                if p.status == "paused"
            ),
            None,
        )
        if paused is None:
            raise CalendarAssistantError("Приостановленный календарь не найден")
        calendar_repo.activate_plan(db, paused)
        self._write_audit(
            db,
            audit_actions.ACTION_AUTOPILOT_CALENDAR_RESUMED,
            project.account_id,
            project_id,
            {"calendar_plan_id": paused.id},
        )
        return {"ok": True, "status": "active"}

    def archive_calendar_plan(
        self,
        db: Session,
        project_id: int,
        calendar_plan_id: int,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Архивировать календарь (без удаления)."""
        project = self._require_project(db, project_id)
        plan = calendar_repo.get_plan_by_id(db, calendar_plan_id)
        if plan is None or plan.project_id != project_id:
            raise CalendarAssistantError("Календарь не найден")
        calendar_repo.archive_plan(db, plan)
        self._write_audit(
            db,
            audit_actions.ACTION_AUTOPILOT_CALENDAR_ARCHIVED,
            project.account_id,
            project_id,
            {"calendar_plan_id": plan.id},
        )
        return {"ok": True, "status": "archived"}

    def estimate_calendar_cost(
        self, db: Session, project_id: int, preview: dict[str, Any]
    ) -> dict[str, Any]:
        """Оценка стоимости календаря (посты/месяц, units/месяц, на сколько хватит баланса)."""
        project = self._require_project(db, project_id)
        built = {
            "weekdays": preview.get("weekdays", []),
            "posts_per_day": preview.get("posts_per_day", 1),
        }
        return self._estimate(db, project.account_id, built)

    # ------------------------------------------------------------------ #
    # Внутреннее: построение календаря                                   #
    # ------------------------------------------------------------------ #

    def _build_calendar(
        self, db: Session, project_id: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        settings = self._resolve_settings()
        preset = str(payload.get("preset") or settings.autopilot_calendar_default_preset_safe)
        if preset not in AUTOPILOT_CALENDAR_PRESETS:
            preset = settings.autopilot_calendar_default_preset_safe
        goal = str(payload.get("goal") or settings.autopilot_calendar_default_goal_safe)
        if goal not in AUTOPILOT_CALENDAR_GOALS:
            goal = settings.autopilot_calendar_default_goal_safe
        spec = CALENDAR_PRESET_DEFS[preset]

        # weekdays: для custom — из payload, иначе из пресета.
        if preset == "custom" and payload.get("weekdays"):
            weekdays = sorted({int(d) for d in payload["weekdays"] if 0 <= int(d) <= 6})
        else:
            weekdays = list(spec["weekdays"])
        posts_per_day = max(
            1,
            min(
                settings.autopilot_calendar_max_posts_per_day_safe,
                int(payload.get("posts_per_day") or spec["posts_per_day"]),
            ),
        )
        timezone = str(payload.get("timezone") or settings.autopilot_calendar_default_timezone_safe)
        time_strategy = str(payload.get("time_strategy") or "platform_default")

        publish_times, source_signals = self._resolve_times(
            db, project_id, preset, spec, time_strategy, payload
        )
        platforms = self._resolve_platforms(db, project_id, payload)

        best_times = source_signals.get("learning_best_times") or []
        confidence = 0.8 if best_times else 0.55
        generated_rules = {
            "preset": preset,
            "goal": goal,
            "weekdays": weekdays,
            "publish_times": publish_times,
            "posts_per_day": posts_per_day,
            "platforms": platforms,
            "timezone": timezone,
        }
        return {
            "preset": preset,
            "goal": goal,
            "weekdays": weekdays,
            "publish_times": publish_times,
            "posts_per_day": posts_per_day,
            "platforms": platforms,
            "timezone": timezone,
            "time_strategy": time_strategy,
            "start_date": payload.get("start_date"),
            "end_date": payload.get("end_date"),
            "generated_rules": generated_rules,
            "source_signals": source_signals,
            "confidence_score": confidence,
        }

    def _resolve_times(
        self,
        db: Session,
        project_id: int,
        preset: str,
        spec: dict[str, Any],
        time_strategy: str,
        payload: dict[str, Any],
    ) -> tuple[list[str], dict[str, Any]]:
        settings = self._resolve_settings()
        signals: dict[str, Any] = {}
        explicit = [str(t).strip() for t in (payload.get("publish_times") or []) if str(t).strip()]
        if (
            time_strategy == "best_known_time"
            and settings.autopilot_calendar_use_learning_best_times
        ):
            best = self._learning_best_times(db, project_id)
            if best:
                signals["learning_best_times"] = best
                return best[: max(1, spec["posts_per_day"])], signals
            signals["learning_best_times"] = []
        if time_strategy in ("fixed_time", "client_custom") and explicit:
            return explicit, signals
        if explicit:
            return explicit, signals
        return list(spec["publish_times"]), signals

    def _resolve_platforms(
        self, db: Session, project_id: int, payload: dict[str, Any]
    ) -> list[str]:
        settings = self._resolve_settings()
        raw = [str(p).strip() for p in (payload.get("platforms") or []) if str(p).strip()]
        if not raw:
            raw = self._project_platforms(db, project_id)
        return raw[: settings.autopilot_calendar_max_platforms_safe]

    # ------------------------------------------------------------------ #
    # Внутреннее: риски / оценки                                         #
    # ------------------------------------------------------------------ #

    def _compute_risks(
        self, db: Session, project_id: int, built: dict[str, Any]
    ) -> list[dict[str, Any]]:
        project = project_repository.get_project_by_id(db, project_id)
        settings = self._resolve_settings()
        media_count = media_asset_repository.count_media_assets(db, project_id=project_id)
        posts_month = self._posts_per_month(built["weekdays"], built["posts_per_day"])
        balance = self._balance_units(db, project.account_id if project else None)
        units_month = self._units_per_month(posts_month)
        risks: list[dict[str, Any]] = []

        if not built["platforms"]:
            risks.append(self._risk("no_platforms", "setup", "Подключите хотя бы одну площадку."))
        if media_count <= 0:
            risks.append(self._risk("no_media", "setup", "Добавьте картинки в медиатеку."))
        elif media_count < posts_month:
            risks.append(
                self._risk(
                    "too_many_posts_for_media",
                    "info",
                    f"Картинок ({media_count}) меньше, чем постов в месяц ({posts_month}).",
                )
            )
        if balance is not None and balance <= 0:
            risks.append(
                self._risk("too_low_balance", "info", "Недостаточно баланса для автопостинга.")
            )
        elif balance is not None and units_month and balance < units_month:
            risks.append(
                self._risk(
                    "too_low_balance",
                    "info",
                    f"Баланса ({balance}) может не хватить на месяц (~{units_month} units).",
                )
            )
        if not self._learning_best_times(db, project_id):
            risks.append(
                self._risk(
                    "no_learning_data",
                    "info",
                    "Данных обучения пока нет — используем базовое время.",
                )
            )
        if any(d in (5, 6) for d in built["weekdays"]):
            risks.append(self._risk("weekend_posts", "info", "Есть публикации в выходные."))
        if not self._platform_live_any(settings, built["platforms"]):
            risks.append(
                self._risk(
                    "live_disabled",
                    "info",
                    "Условия публикации выключены: посты пойдут на проверку.",
                )
            )
        if not (built.get("timezone") or "").strip():
            risks.append(self._risk("timezone_missing", "info", "Не указан часовой пояс."))
        return risks

    def _estimate(
        self, db: Session, account_id: int | None, built: dict[str, Any]
    ) -> dict[str, Any]:
        posts_month = self._posts_per_month(
            built.get("weekdays", []), built.get("posts_per_day", 1)
        )
        units_post = self._units_per_post()
        units_month = units_post * posts_month
        balance = self._balance_units(db, account_id)
        approx_left = None
        if balance is not None and units_post > 0:
            approx_left = int(balance // units_post)
        return {
            "estimated_posts_per_month": posts_month,
            "estimated_units_per_month": units_month,
            "estimated_media_needed": posts_month,
            "units_per_post": units_post,
            "balance_units": balance,
            "approx_posts_left": approx_left,
        }

    @staticmethod
    def _posts_per_month(weekdays: list[Any], posts_per_day: int) -> int:
        days = len([d for d in weekdays if 0 <= int(d) <= 6])
        return int(round(days * max(1, posts_per_day) * _WEEKS_PER_MONTH))

    def _units_per_post(self) -> int:
        try:
            from app.services.unit_economics_service import get_unit_economics_service

            return int(get_unit_economics_service().estimate_schedule_generation_units(1))
        except Exception:  # noqa: BLE001 — оценка не критична
            return 5

    def _units_per_month(self, posts_month: int) -> int:
        return self._units_per_post() * posts_month

    # ------------------------------------------------------------------ #
    # Внутреннее: сигналы проекта                                        #
    # ------------------------------------------------------------------ #

    def _project_platforms(self, db: Session, project_id: int) -> list[str]:
        try:
            from app.services.platform_connection_service import get_platform_connection_service

            conns = get_platform_connection_service().list_connections(db, project_id)
            return [
                c["platform_key"]
                for c in conns
                if c.get("connected") and c["platform_key"] != "yandex_disk"
            ]
        except Exception:  # noqa: BLE001 — отсутствие подключений не критично
            return []

    def _learning_best_times(self, db: Session, project_id: int) -> list[str]:
        try:
            from app.repositories import client_learning_repository

            profile = client_learning_repository.get_profile(db, project_id)
            if profile is not None and profile.best_publish_times:
                return [str(t) for t in profile.best_publish_times][:3]
        except Exception:  # noqa: BLE001 — обучение не критично
            logger.warning("learning best times unavailable for project_id=%s", project_id)
        return []

    def _balance_units(self, db: Session, account_id: int | None) -> int | None:
        if account_id is None:
            return None
        try:
            from app.services.billing_service import BillingService

            account = BillingService().get_balance(db, account_id)
            return int(getattr(account, "balance_units", 0) or 0)
        except Exception:  # noqa: BLE001 — баланс не критичен
            return None

    def _autopilot_profile_id(self, db: Session, project_id: int) -> int | None:
        try:
            from app.repositories import autopilot_repository

            profile = autopilot_repository.get_profile_by_project_id(db, project_id)
            return profile.id if profile is not None else None
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------ #
    # Внутреннее: дашборд-хелперы                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _upcoming_dates(weekdays: list[Any], publish_times: list[Any]) -> list[dict[str, Any]]:
        """Ближайшие 7 плановых дат (без реального времени — детерминированно, без now())."""
        wd = sorted({int(d) for d in weekdays if 0 <= int(d) <= 6})
        time = str(publish_times[0]) if publish_times else "10:00"
        return [{"weekday": _WEEKDAY_LABELS[d], "time": time} for d in wd][:7]

    def _next_best_action(
        self, db: Session, project_id: int, active: AutopilotCalendarPlan | None
    ) -> dict[str, Any]:
        if active is None:
            return {"action": "create_calendar", "label": "Создайте календарь автопостинга"}
        if active.status == "draft":
            return {"action": "apply_calendar", "label": "Примените календарь"}
        return {"action": "open_autopilot", "label": "Откройте автопилот"}

    @staticmethod
    def _client_summary(active: AutopilotCalendarPlan | None) -> dict[str, Any]:
        if active is None:
            return {"headline": "Календарь не создан", "tone": "setup"}
        labels = "/".join(_WEEKDAY_LABELS[d] for d in (active.weekdays or []) if 0 <= int(d) <= 6)
        times = ", ".join(str(t) for t in (active.publish_times or [])) or "10:00"
        return {
            "headline": f"Календарь активен: {labels or '—'} {times}",
            "tone": "active" if active.status == "active" else "draft",
        }

    @staticmethod
    def _platform_live_any(settings: Any, platforms: list[str]) -> bool:
        attr = {
            "telegram": "telegram_live_publishing_enabled",
            "vk": "vk_live_publishing_enabled",
            "instagram": "instagram_live_publishing_enabled",
        }
        return any(bool(getattr(settings, attr.get(p, ""), False)) for p in platforms)

    # ------------------------------------------------------------------ #
    # Внутреннее: инфраструктура                                         #
    # ------------------------------------------------------------------ #

    def _require_project(self, db: Session, project_id: int) -> Any:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise CalendarAssistantError("Проект не найден")
        return project

    @staticmethod
    def _risk(risk_type: str, severity: str, message: str) -> dict[str, Any]:
        return {"type": risk_type, "severity": severity, "message": message}

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

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
            entity_type="autopilot_calendar",
            metadata=metadata or {},
        )


def get_autopilot_calendar_assistant_service() -> AutopilotCalendarAssistantService:
    """DI-фабрика сервиса Calendar Assistant."""
    return AutopilotCalendarAssistantService()
