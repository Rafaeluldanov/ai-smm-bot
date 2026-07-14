"""Сервис мониторинга live-автопилота и kill switch — v0.6.1.

Клиентский слой «как себя чувствует автопилот»: наблюдение за live-попытками за окно, здоровье,
инциденты (повторные сбои/блокировки/низкий баланс) и «стоп-кран» (пауза/возобновление автопилота
и площадок). Это журнал наблюдения + управление ПАУЗОЙ, а не включатель live.

БЕЗОПАСНОСТЬ (инварианты):
- Мониторинг НЕ включает и НЕ обходит глобальные ``*_LIVE_PUBLISHING_ENABLED`` (админ-флаги);
- kill switch останавливает публикацию, переключая состояние, которое движок УЖЕ учитывает
  (per-project/per-platform live через ``LiveReadinessService`` + пауза профиля автопилота);
- «resume» НЕ перевзводит реальную публикацию: live для проекта остаётся выключенным, пока клиент
  осознанно не включит его снова через готовность (отдельное подтверждение + порог);
- авто-пауза выключена по умолчанию (только preview); dry-run по умолчанию не пишет в БД;
- секретов/токенов/сырых payload не хранит и не печатает.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import autopilot_repository as autopilot_repo
from app.repositories import live_autopilot_monitoring_repository as monitor_repo
from app.repositories import live_readiness_repository as readiness_repo
from app.repositories import project_repository
from app.services import audit_log_service as audit_actions
from app.services.billing_service import USAGE_AUTO_PUBLISH_ACTION

if TYPE_CHECKING:  # pragma: no cover - только для типов
    from datetime import datetime

    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

# Telegram — первый live-канал (см. v0.6.0); мониторинг здоровья считаем по нему.
_PRIMARY_PLATFORM = "telegram"

# Минимум сбоев, чтобы по доле сбоев опустить здоровье до «degraded» (одиночный сбой → «warning»).
_MIN_FAILURES_FOR_DEGRADED = 2


class LiveAutopilotMonitoringError(Exception):
    """Ошибка мониторинга автопилота (нет проекта/доступа/подтверждения) — API → 400/404."""


class LiveAutopilotMonitoringService:
    """Наблюдение за live-автопилотом, инциденты и kill switch (пауза/возобновление)."""

    def __init__(
        self,
        readiness_service: Any | None = None,
        autopilot_service: Any | None = None,
        billing_service: Any | None = None,
        notification_service: Any | None = None,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._readiness = readiness_service
        self._autopilot = autopilot_service
        self._billing = billing_service
        self._notification = notification_service
        self._audit = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Наблюдение: health-check + снимок                                  #
    # ------------------------------------------------------------------ #

    def run_health_check(
        self,
        db: Session,
        project_id: int,
        current_user_id: int | None = None,
        dry_run: bool | None = None,
        *,
        worker_owner_id: int | None = None,
        is_worker: bool = False,
    ) -> dict[str, Any]:
        """Собрать снимок здоровья автопилота за окно наблюдения.

        При ``dry_run`` (по умолчанию из настроек) НИЧЕГО не пишет в БД: только считает. Иначе
        сохраняет снимок, при необходимости заводит инциденты и (если разрешено) авто-паузу.
        """
        project = self._require_project(db, project_id)
        settings = self._resolve_settings()
        if dry_run is None:
            dry_run = settings.live_autopilot_monitoring_dry_run_effective
        computed = self._compute_health(db, project, settings)

        created_snapshot = False
        incidents_created: list[dict[str, Any]] = []
        auto_pause_result: dict[str, Any] | None = None
        if not dry_run and settings.live_autopilot_monitoring_enabled_effective:
            self._persist_snapshot(db, project, computed)
            created_snapshot = True
            incidents_created = self._maybe_open_incidents(db, project, computed, settings)
            auto_pause_result = self._maybe_auto_pause(
                db, project, computed, settings, current_user_id=current_user_id or worker_owner_id
            )
            self._write_audit(
                db,
                audit_actions.ACTION_LIVE_MONITORING_SNAPSHOT_CREATED,
                project.account_id,
                project_id,
                {
                    "health_status": computed["health_status"],
                    "failure_rate": computed["public"]["failure_rate"],
                    "incidents_created": len(incidents_created),
                    "worker": bool(is_worker or worker_owner_id is not None),
                },
            )

        result = dict(computed["public"])
        result.update(
            {
                "project_id": project_id,
                "dry_run": bool(dry_run),
                "snapshot_created": created_snapshot,
                "blockers": computed["blockers"],
                "warnings": computed["warnings"],
                "incidents_created": incidents_created,
                "auto_pause": auto_pause_result,
                "note": computed["note"],
            }
        )
        return result

    def build_dashboard(self, db: Session, project_id: int) -> dict[str, Any]:
        """Клиентский дашборд мониторинга (без записи в БД): здоровье, инциденты, стоп-кран."""
        project = self._require_project(db, project_id)
        settings = self._resolve_settings()
        computed = self._compute_health(db, project, settings)
        open_incidents = monitor_repo.list_open_incidents_for_project(db, project_id)
        latest = monitor_repo.get_latest_snapshot_for_project(db, project_id)
        self._write_audit(
            db,
            audit_actions.ACTION_LIVE_MONITORING_DASHBOARD_VIEWED,
            project.account_id,
            project_id,
            {"health_status": computed["health_status"]},
        )
        public = dict(computed["public"])
        active_incidents = [monitor_repo.public_incident_view(i) for i in open_incidents]
        return {
            "project_id": project_id,
            # --- Плоские клиентские поля (спека v0.6.1) --- #
            "monitoring_enabled": settings.live_autopilot_monitoring_enabled_effective,
            "dry_run": settings.live_autopilot_monitoring_dry_run_effective,
            "health_status": computed["health_status"],
            "health_label": _HEALTH_LABELS.get(
                computed["health_status"], computed["health_status"]
            ),
            "publish_attempts": public["total_attempts"],
            "successful_attempts": public["published_count"],
            "failed_attempts": public["failed_count"],
            "failure_rate": public["failure_rate"],
            "incidents_count": public["open_incident_count"],
            "active_incidents": active_incidents,
            "autopilot_paused": public["autopilot_paused"],
            "platforms": self._platform_states(computed),
            "recommendations": self._recommendations(computed),
            # --- Расширенные блоки --- #
            "snapshot": public,
            "blockers": computed["blockers"],
            "warnings": computed["warnings"],
            "open_incidents": active_incidents,
            "open_incident_count": public["open_incident_count"],
            "critical_incident_count": public["critical_incident_count"],
            "kill_switch": self._kill_switch_state(computed, settings),
            "auto_pause": self.preview_auto_pause(db, project_id, _computed=computed),
            "controls": self._controls(settings),
            "last_snapshot_at": latest.created_at.isoformat()
            if latest and latest.created_at
            else None,
            "next_best_action": computed["next_best_action"],
            "client_summary": computed["client_summary"],
            "note": computed["note"],
        }

    def analyze_project_health(self, db: Session, project_id: int) -> dict[str, Any]:
        """Проанализировать здоровье проекта за окно (без записи в БД).

        Возвращает метрики: статус здоровья, счётчики попыток, доля сбоев, блокеры/предупреждения.
        """
        project = self._require_project(db, project_id)
        settings = self._resolve_settings()
        computed = self._compute_health(db, project, settings)
        public = computed["public"]
        return {
            "project_id": project_id,
            "health_status": computed["health_status"],
            "total_attempts": public["total_attempts"],
            "successful_attempts": public["published_count"],
            "failed_attempts": public["failed_count"],
            "blocked_attempts": public["blocked_count"],
            "skipped_attempts": public["skipped_count"],
            "success_rate": public["success_rate"],
            "failure_rate": public["failure_rate"],
            "autopilot_paused": public["autopilot_paused"],
            "blockers": computed["blockers"],
            "warnings": computed["warnings"],
        }

    def create_snapshot(self, db: Session, project_id: int) -> dict[str, Any]:
        """Создать и сохранить снимок мониторинга (явное действие, пишет в БД)."""
        project = self._require_project(db, project_id)
        settings = self._resolve_settings()
        computed = self._compute_health(db, project, settings)
        snapshot = self._persist_snapshot(db, project, computed)
        self._write_audit(
            db,
            audit_actions.ACTION_LIVE_MONITORING_SNAPSHOT_CREATED,
            project.account_id,
            project_id,
            {"health_status": computed["health_status"], "manual": True},
        )
        return monitor_repo.public_snapshot_view(snapshot)

    def detect_incidents(self, db: Session, project_id: int) -> dict[str, Any]:
        """Проверить пороги и завести инциденты (явное действие, пишет в БД). Дедуп по окну."""
        project = self._require_project(db, project_id)
        settings = self._resolve_settings()
        computed = self._compute_health(db, project, settings)
        created = self._maybe_open_incidents(db, project, computed, settings)
        return {"project_id": project_id, "incidents_created": created, "count": len(created)}

    def list_snapshots(
        self, db: Session, project_id: int, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """Список снимков мониторинга проекта (свежие первыми)."""
        self._require_project(db, project_id)
        rows = monitor_repo.list_snapshots_for_project(db, project_id, limit=limit, offset=offset)
        return {
            "project_id": project_id,
            "snapshots": [monitor_repo.public_snapshot_view(s) for s in rows],
            "summary": monitor_repo.build_snapshot_summary(db, project_id),
        }

    # ------------------------------------------------------------------ #
    # Инциденты                                                          #
    # ------------------------------------------------------------------ #

    def list_incidents(
        self,
        db: Session,
        project_id: int,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Список инцидентов проекта (с опциональным фильтром по статусу)."""
        self._require_project(db, project_id)
        rows = monitor_repo.list_incidents_for_project(
            db, project_id, status=status, limit=limit, offset=offset
        )
        open_count, critical = monitor_repo.count_open_incidents(db, project_id)
        return {
            "project_id": project_id,
            "incidents": [monitor_repo.public_incident_view(i) for i in rows],
            "open_incident_count": open_count,
            "critical_incident_count": critical,
        }

    def get_incident(self, db: Session, incident_id: int) -> dict[str, Any]:
        """Инцидент по id (безопасное представление)."""
        incident = monitor_repo.get_incident_by_id(db, incident_id)
        if incident is None:
            raise LiveAutopilotMonitoringError("Инцидент не найден")
        return monitor_repo.public_incident_view(incident)

    def acknowledge_incident(
        self, db: Session, incident_id: int, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """Подтвердить инцидент (клиент увидел и разбирается)."""
        return self._transition_incident(
            db,
            incident_id,
            monitor_repo.acknowledge_incident,
            audit_actions.ACTION_LIVE_MONITORING_INCIDENT_ACKNOWLEDGED,
            current_user_id,
        )

    def resolve_incident(
        self, db: Session, incident_id: int, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """Отметить инцидент решённым."""
        return self._transition_incident(
            db,
            incident_id,
            monitor_repo.resolve_incident,
            audit_actions.ACTION_LIVE_MONITORING_INCIDENT_RESOLVED,
            current_user_id,
        )

    def ignore_incident(
        self, db: Session, incident_id: int, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """Отметить инцидент проигнорированным."""
        return self._transition_incident(
            db,
            incident_id,
            monitor_repo.ignore_incident,
            audit_actions.ACTION_LIVE_MONITORING_INCIDENT_IGNORED,
            current_user_id,
        )

    # ------------------------------------------------------------------ #
    # Kill switch: пауза / возобновление                                #
    # ------------------------------------------------------------------ #

    def pause_project_autopilot(
        self,
        db: Session,
        project_id: int,
        confirmation: str | None = None,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Остановить автопилот проекта: пауза профиля + выключение per-project/full-auto live.

        Это ОСТАНАВЛИВАЕТ реальную публикацию немедленно (движок учитывает эти переключатели).
        Глобальные live-флаги не трогает.
        """
        project = self._require_project(db, project_id)
        settings = self._resolve_settings()
        self._guard_kill_switch(settings)
        self._require_pause_confirmation(confirmation, settings)
        # 1) Пауза автопилота (профиль: is_enabled=False, status=paused).
        with _soft():
            self._autopilot_service().pause_autopilot(db, project_id, current_user_id)
        # 2) Выключить per-project live и full-auto (движок сразу перестаёт публиковать вживую).
        readiness = self._readiness_service()
        readiness.disable_project_live(db, project_id, current_user_id)
        readiness.disable_full_auto_live(db, project_id, current_user_id)
        self._write_audit(
            db,
            audit_actions.ACTION_LIVE_MONITORING_PROJECT_PAUSED,
            project.account_id,
            project_id,
            {"live_disabled": True},
        )
        return {
            "ok": True,
            "project_id": project_id,
            "autopilot_paused": True,
            "project_live_enabled": False,
            "full_auto_live_enabled": False,
            "units_charged": 0,
            "note": (
                "Автопилот остановлен: черновики и реальная публикация приостановлены. "
                "Глобальные условия публикации не изменялись."
            ),
        }

    def resume_project_autopilot(
        self,
        db: Session,
        project_id: int,
        confirmation: str | None = None,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Возобновить автопилот проекта (черновики). Реальную публикацию НЕ перевзводит.

        Live для проекта остаётся выключенным — включите его отдельно через готовность
        (с подтверждением и проверкой), чтобы возобновление не запустило реальную отправку случайно.
        """
        project = self._require_project(db, project_id)
        settings = self._resolve_settings()
        self._guard_kill_switch(settings)
        self._require_resume_confirmation(confirmation, settings)
        started: dict[str, Any] = {}
        with _soft():
            started = self._autopilot_service().start_autopilot(db, project_id, current_user_id)
        self._write_audit(
            db,
            audit_actions.ACTION_LIVE_MONITORING_PROJECT_RESUMED,
            project.account_id,
            project_id,
            {"autopilot_ok": bool(started.get("ok"))},
        )
        return {
            "ok": bool(started.get("ok", True)),
            "project_id": project_id,
            "autopilot_status": started.get("status", "running"),
            "live_re_enabled": False,
            "blockers": started.get("blockers", []),
            "units_charged": 0,
            "note": (
                "Автопилот возобновлён (черновики). Реальная публикация остаётся ВЫКЛЮЧЕННОЙ — "
                "включите её осознанно через «Готовность к автопубликации»."
            ),
        }

    def pause_autopilot(
        self,
        db: Session,
        project_id: int,
        confirmation_text: str = "",
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Спека-псевдоним ``pause_project_autopilot`` (стоп-кран проекта)."""
        return self.pause_project_autopilot(
            db, project_id, confirmation=confirmation_text, current_user_id=current_user_id
        )

    def resume_autopilot(
        self,
        db: Session,
        project_id: int,
        confirmation_text: str = "",
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Спека-псевдоним ``resume_project_autopilot`` (возобновление проекта)."""
        return self.resume_project_autopilot(
            db, project_id, confirmation=confirmation_text, current_user_id=current_user_id
        )

    def preview_pause(self, db: Session, project_id: int) -> dict[str, Any]:
        """Предпросмотр стоп-крана: НЕ ставит паузу, только показывает, что произойдёт."""
        project = self._require_project(db, project_id)
        settings = self._resolve_settings()
        affected = [
            p.platform_key
            for p in readiness_repo.list_platform_profiles(db, project_id)
            if p.platform_live_enabled
        ]
        gate = self._readiness_service().build_effective_live_gate(
            db, project_id, _PRIMARY_PLATFORM
        )
        if gate.get("project_live_enabled") and _PRIMARY_PLATFORM not in affected:
            affected.append(_PRIMARY_PLATFORM)
        return {
            "allowed": False,  # предпросмотр никогда не выполняет паузу
            "project_id": project_id,
            "reason": (
                "Предпросмотр стоп-крана: пауза остановит черновики и реальную публикацию для "
                "проекта. Глобальные условия публикации не изменятся."
            ),
            "affected_platforms": affected,
            "kill_switch_enabled": settings.live_autopilot_kill_switch_enabled_effective,
            "confirmation_required": settings.live_autopilot_kill_switch_require_confirmation,
            "confirmation_text": settings.live_autopilot_pause_confirmation_text_safe,
            "account_id": project.account_id,
        }

    def pause_platform_live(
        self,
        db: Session,
        project_id: int,
        platform_key: str,
        confirmation: str | None = None,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Выключить live для одной площадки (черновики продолжают создаваться)."""
        project = self._require_project(db, project_id)
        settings = self._resolve_settings()
        self._guard_kill_switch(settings)
        self._require_pause_confirmation(confirmation, settings)
        platform_key = str(platform_key or "").strip().lower()
        self._readiness_service().disable_platform_live(
            db, project_id, platform_key, current_user_id
        )
        self._write_audit(
            db,
            audit_actions.ACTION_LIVE_MONITORING_PLATFORM_PAUSED,
            project.account_id,
            project_id,
            {"platform": platform_key},
        )
        return {
            "ok": True,
            "project_id": project_id,
            "platform_key": platform_key,
            "platform_live_enabled": False,
            "units_charged": 0,
            "note": f"Реальная публикация в «{platform_key}» приостановлена.",
        }

    def resume_platform_live(
        self,
        db: Session,
        project_id: int,
        platform_key: str,
        confirmation: str,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Возобновить live для площадки — через готовность (подтверждение + проверка).

        Делегирует ``LiveReadinessService.enable_platform_live``: перевзвод реальной публикации
        возможен только если площадка снова прошла проверку и введено подтверждение готовности.
        Обхода safety-gates здесь нет.
        """
        project = self._require_project(db, project_id)
        settings = self._resolve_settings()
        self._guard_kill_switch(settings)
        platform_key = str(platform_key or "").strip().lower()
        result = self._readiness_service().enable_platform_live(
            db, project_id, platform_key, confirmation, current_user_id
        )
        self._write_audit(
            db,
            audit_actions.ACTION_LIVE_MONITORING_PLATFORM_RESUMED,
            project.account_id,
            project_id,
            {"platform": platform_key},
        )
        return {
            "ok": bool(result.get("ok", True)),
            "project_id": project_id,
            "platform_key": platform_key,
            "platform_live_enabled": bool(result.get("platform_live_enabled")),
            "units_charged": 0,
            "note": "Live для площадки возобновлён после проверки готовности.",
        }

    # ------------------------------------------------------------------ #
    # Авто-пауза (по умолчанию выключена → только preview)               #
    # ------------------------------------------------------------------ #

    def preview_auto_pause(
        self, db: Session, project_id: int, *, _computed: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Показать, сработала бы авто-пауза (без действия)."""
        settings = self._resolve_settings()
        if _computed is None:
            project = self._require_project(db, project_id)
            _computed = self._compute_health(db, project, settings)
        would, reason = self._auto_pause_decision(_computed, settings)
        return {
            "enabled": settings.live_autopilot_auto_pause_enabled_effective,
            "would_pause": bool(would),
            "reason": reason,
            "failures_threshold": settings.live_autopilot_auto_pause_failures_threshold,
            "critical_only": bool(settings.live_autopilot_auto_pause_critical_only),
            "current_failures": _computed["public"]["failed_count"],
            "note": (
                "Авто-пауза включена: при повторных сбоях автопилот будет остановлен автоматически."
                if settings.live_autopilot_auto_pause_enabled_effective
                else "Авто-пауза выключена: система только предупреждает, решение за вами."
            ),
        }

    # ------------------------------------------------------------------ #
    # Внутреннее: расчёт здоровья                                        #
    # ------------------------------------------------------------------ #

    def _compute_health(self, db: Session, project: Any, settings: Settings) -> dict[str, Any]:
        from datetime import UTC, datetime, timedelta

        project_id = project.id
        now = datetime.now(UTC)
        since = now - timedelta(seconds=settings.live_autopilot_monitoring_window_seconds)
        # Здоровье считаем по первичному live-каналу (снимок/инциденты помечены им же), чтобы сбои
        # другой площадки не приписывались Telegram. Ограничиваем размер выборки настройкой.
        stats = monitor_repo.aggregate_attempts_for_window(
            db,
            project_id,
            since,
            platform_key=_PRIMARY_PLATFORM,
            max_attempts=settings.live_autopilot_monitoring_max_attempts_for_health,
        )

        gate = self._readiness_service().build_effective_live_gate(
            db, project_id, _PRIMARY_PLATFORM
        )
        autopilot_profile = autopilot_repo.get_profile_by_project_id(db, project_id)
        autopilot_paused = bool(
            autopilot_profile is not None
            and (not autopilot_profile.is_enabled or autopilot_profile.status == "paused")
        )
        project_live = bool(gate.get("project_live_enabled"))
        full_auto_live = bool(gate.get("full_auto_live_enabled"))
        open_count, critical_count = monitor_repo.count_open_incidents(db, project_id)

        balance_units, approx_posts_left = self._balance_snapshot(db, project.account_id)

        health = self._health_status(
            autopilot_paused=autopilot_paused,
            real_attempts=stats["real_attempts"],
            failed_count=stats["failed"],
            failure_rate=stats["failure_rate"],
            critical_incidents=critical_count,
            settings=settings,
        )
        blockers = self._build_blockers(stats, gate, balance_units, approx_posts_left, settings)
        warnings = self._build_warnings(stats, autopilot_paused, settings)

        public = {
            "health_status": health,
            "platform_key": _PRIMARY_PLATFORM,
            "period_start": since.isoformat(),
            "period_end": now.isoformat(),
            "total_attempts": stats["total"],
            "published_count": stats["published"],
            "blocked_count": stats["blocked"],
            "failed_count": stats["failed"],
            "skipped_count": stats["skipped"],
            "success_rate": stats["success_rate"],
            "failure_rate": stats["failure_rate"],
            "last_attempt_id": stats["last_attempt_id"],
            "last_published_at": _iso(stats["last_published_at"]),
            "last_failed_at": _iso(stats["last_failed_at"]),
            "last_blocked_at": _iso(stats["last_blocked_at"]),
            "open_incident_count": open_count,
            "critical_incident_count": critical_count,
            "balance_units": balance_units,
            "approx_posts_left": approx_posts_left,
            "project_live_enabled": project_live,
            "full_auto_live_enabled": full_auto_live,
            "autopilot_paused": autopilot_paused,
            "can_publish_live": bool(gate.get("can_publish_live")),
        }
        return {
            "public": public,
            "stats": stats,
            "gate": gate,
            "since": since,
            "now": now,
            "health_status": health,
            "blockers": blockers,
            "warnings": warnings,
            "autopilot_paused": autopilot_paused,
            "balance_units": balance_units,
            "approx_posts_left": approx_posts_left,
            "next_best_action": self._next_action(health, blockers, autopilot_paused),
            "client_summary": self._client_summary(health),
            "note": (
                "Мониторинг только наблюдает и умеет ставить автопилот на паузу. "
                "Глобальные условия публикации он не включает и не меняет."
            ),
        }

    def _persist_snapshot(self, db: Session, project: Any, computed: dict[str, Any]) -> Any:
        public = computed["public"]
        return monitor_repo.create_snapshot(
            db,
            account_id=project.account_id,
            project_id=project.id,
            platform_key=_PRIMARY_PLATFORM,
            health_status=public["health_status"],
            period_start=computed["since"],
            period_end=computed["now"],
            total_attempts=public["total_attempts"],
            published_count=public["published_count"],
            blocked_count=public["blocked_count"],
            failed_count=public["failed_count"],
            skipped_count=public["skipped_count"],
            success_rate=public["success_rate"],
            failure_rate=public["failure_rate"],
            last_attempt_id=public["last_attempt_id"],
            last_published_at=computed["stats"]["last_published_at"],
            last_failed_at=computed["stats"]["last_failed_at"],
            last_blocked_at=computed["stats"]["last_blocked_at"],
            open_incident_count=public["open_incident_count"],
            critical_incident_count=public["critical_incident_count"],
            balance_units=public["balance_units"],
            approx_posts_left=public["approx_posts_left"],
            project_live_enabled=public["project_live_enabled"],
            full_auto_live_enabled=public["full_auto_live_enabled"],
            platform_live_statuses={_PRIMARY_PLATFORM: computed["gate"]},
            readiness_status={"can_publish_live": public["can_publish_live"]},
            blockers=computed["blockers"],
            warnings=computed["warnings"],
            summary={
                "health_status": public["health_status"],
                "failure_rate": public["failure_rate"],
                "autopilot_paused": public["autopilot_paused"],
            },
        )

    def _maybe_open_incidents(
        self, db: Session, project: Any, computed: dict[str, Any], settings: Settings
    ) -> list[dict[str, Any]]:
        if not settings.live_autopilot_incidents_enabled_effective:
            return []
        public = computed["public"]
        opened: list[dict[str, Any]] = []
        dedup = settings.live_autopilot_incident_dedup_seconds

        failed = public["failed_count"]
        if failed >= settings.live_autopilot_auto_pause_failures_threshold:
            critical = (
                public["failure_rate"] >= settings.live_autopilot_monitoring_failure_critical_rate
            )
            incident, created = monitor_repo.create_or_increment_incident(
                db,
                account_id=project.account_id,
                project_id=project.id,
                incident_type="repeated_publish_failures",
                severity="critical" if critical else "high",
                title="Повторные сбои публикации",
                message=(
                    f"За период наблюдения зафиксировано {failed} сбоев публикации "
                    f"(доля сбоев {int(round(public['failure_rate'] * 100))}%)."
                ),
                platform_key=_PRIMARY_PLATFORM,
                dedup_seconds=dedup,
                recommended_action="Проверьте подключение площадки и повторите позже.",
            )
            self._record_incident_audit(db, project, incident, created)
            if created:
                opened.append(monitor_repo.public_incident_view(incident))

        approx = public["approx_posts_left"]
        if approx is not None and approx <= 2:
            incident, created = monitor_repo.create_or_increment_incident(
                db,
                account_id=project.account_id,
                project_id=project.id,
                incident_type="balance_low",
                severity="medium",
                title="Заканчивается баланс",
                message=f"Баланса хватит примерно на {approx} публикаций. Пополните счёт.",
                dedup_seconds=dedup,
                recommended_action="Пополните баланс, чтобы автопилот не остановился.",
            )
            self._record_incident_audit(db, project, incident, created)
            if created:
                opened.append(monitor_repo.public_incident_view(incident))
        return opened

    def _maybe_auto_pause(
        self,
        db: Session,
        project: Any,
        computed: dict[str, Any],
        settings: Settings,
        current_user_id: int | None = None,
    ) -> dict[str, Any] | None:
        would, reason = self._auto_pause_decision(computed, settings)
        if not would:
            return None
        if not settings.live_autopilot_auto_pause_enabled_effective:
            # Авто-пауза выключена: только фиксируем, что сработала бы (без действия).
            self._write_audit(
                db,
                audit_actions.ACTION_LIVE_MONITORING_AUTO_PAUSE_PREVIEWED,
                project.account_id,
                project.id,
                {"reason": reason},
            )
            return {"paused": False, "previewed": True, "reason": reason}
        if computed["autopilot_paused"]:
            return {"paused": False, "already_paused": True, "reason": reason}
        # Реально останавливаем (системная пауза без подтверждения — инициировано защитой).
        with _soft():
            self._autopilot_service().pause_autopilot(db, project.id, current_user_id)
        readiness = self._readiness_service()
        readiness.disable_project_live(db, project.id, current_user_id)
        readiness.disable_full_auto_live(db, project.id, current_user_id)
        for incident in monitor_repo.list_open_incidents_for_project(db, project.id):
            if incident.incident_type == "repeated_publish_failures":
                monitor_repo.mark_auto_paused(db, incident, reason or "auto_pause")
        self._write_audit(
            db,
            audit_actions.ACTION_LIVE_MONITORING_AUTO_PAUSED,
            project.account_id,
            project.id,
            {"reason": reason},
        )
        return {"paused": True, "reason": reason}

    def _auto_pause_decision(
        self, computed: dict[str, Any], settings: Settings
    ) -> tuple[bool, str | None]:
        public = computed["public"]
        failed = public["failed_count"]
        if failed < settings.live_autopilot_auto_pause_failures_threshold:
            return False, None
        if (
            settings.live_autopilot_auto_pause_critical_only
            and public["failure_rate"] < settings.live_autopilot_monitoring_failure_critical_rate
        ):
            return False, None
        return True, "repeated_publish_failures"

    # ------------------------------------------------------------------ #
    # Внутреннее: строки/статусы                                         #
    # ------------------------------------------------------------------ #

    def _health_status(
        self,
        *,
        autopilot_paused: bool,
        real_attempts: int,
        failed_count: int,
        failure_rate: float,
        critical_incidents: int,
        settings: Settings,
    ) -> str:
        if autopilot_paused:
            return "paused"
        if critical_incidents > 0:
            return "degraded"
        if real_attempts == 0:
            return "unknown"
        # Мин. выборка: одиночный сбой (1 из 1) не должен опускать здоровье до «degraded» —
        # для «degraded» по доле сбоев нужно ≥2 сбоя, иначе максимум «warning».
        if (
            failure_rate >= settings.live_autopilot_monitoring_failure_critical_rate
            and failed_count >= _MIN_FAILURES_FOR_DEGRADED
        ):
            return "degraded"
        if failure_rate >= settings.live_autopilot_monitoring_failure_warning_rate:
            return "warning"
        return "healthy"

    def _build_blockers(
        self,
        stats: dict[str, Any],
        gate: dict[str, Any],
        balance_units: int | None,
        approx_posts_left: int | None,
        settings: Settings,
    ) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        if stats["failed"] >= settings.live_autopilot_auto_pause_failures_threshold:
            blockers.append(
                _blk(
                    "repeated_publish_failures",
                    "critical"
                    if stats["failure_rate"]
                    >= settings.live_autopilot_monitoring_failure_critical_rate
                    else "high",
                    f"Повторные сбои публикации: {stats['failed']} за период.",
                )
            )
        if approx_posts_left is not None and approx_posts_left <= 2:
            blockers.append(_blk("balance_low", "high", "Заканчивается баланс — пополните счёт."))
        return blockers

    def _build_warnings(
        self, stats: dict[str, Any], autopilot_paused: bool, settings: Settings
    ) -> list[dict[str, Any]]:
        warnings: list[dict[str, Any]] = []
        if autopilot_paused:
            warnings.append(_blk("autopilot_paused", "info", "Автопилот на паузе."))
        if 0 < stats["failed"] < settings.live_autopilot_auto_pause_failures_threshold:
            warnings.append(
                _blk("some_failures", "info", f"Есть отдельные сбои публикации: {stats['failed']}.")
            )
        return warnings

    def _kill_switch_state(self, computed: dict[str, Any], settings: Settings) -> dict[str, Any]:
        public = computed["public"]
        return {
            "enabled": settings.live_autopilot_kill_switch_enabled_effective,
            "require_confirmation": settings.live_autopilot_kill_switch_require_confirmation,
            "pause_confirmation_text": settings.live_autopilot_pause_confirmation_text_safe,
            "resume_confirmation_text": settings.live_autopilot_resume_confirmation_text_safe,
            "autopilot_paused": public["autopilot_paused"],
            "project_live_enabled": public["project_live_enabled"],
            "full_auto_live_enabled": public["full_auto_live_enabled"],
            "can_publish_live": public["can_publish_live"],
        }

    def _controls(self, settings: Settings) -> dict[str, Any]:
        return {
            "kill_switch_enabled": settings.live_autopilot_kill_switch_enabled_effective,
            "auto_pause_enabled": settings.live_autopilot_auto_pause_enabled_effective,
            "monitoring_dry_run": settings.live_autopilot_monitoring_dry_run_effective,
            "window_hours": settings.live_autopilot_monitoring_window_hours,
        }

    @staticmethod
    def _platform_states(computed: dict[str, Any]) -> list[dict[str, Any]]:
        """Состояние live по площадкам для дашборда (первичный канал)."""
        gate = computed["gate"]
        return [
            {
                "platform_key": _PRIMARY_PLATFORM,
                "live_enabled": bool(gate.get("platform_live_enabled")),
                "project_live_enabled": bool(gate.get("project_live_enabled")),
                "readiness_ready": bool(gate.get("readiness_ready")),
                "can_publish_live": bool(gate.get("can_publish_live")),
            }
        ]

    @staticmethod
    def _recommendations(computed: dict[str, Any]) -> list[str]:
        """Понятные клиенту рекомендации (из next_best_action + блокеров), без дублей."""
        candidates = [computed["next_best_action"]["label"]]
        candidates.extend(b["message"] for b in computed["blockers"])
        result: list[str] = []
        for rec in candidates:
            if rec not in result:
                result.append(rec)
        return result

    @staticmethod
    def _next_action(
        health: str, blockers: list[dict[str, Any]], autopilot_paused: bool
    ) -> dict[str, Any]:
        if autopilot_paused:
            return {
                "code": "resume",
                "label": "Автопилот на паузе — возобновите, когда будете готовы.",
            }
        if any(b["type"] == "balance_low" for b in blockers):
            return {"code": "topup", "label": "Пополните баланс."}
        if any(b["type"] == "repeated_publish_failures" for b in blockers):
            return {"code": "investigate", "label": "Проверьте площадку: есть повторные сбои."}
        if health == "healthy":
            return {"code": "ok", "label": "Всё работает штатно."}
        return {"code": "watch", "label": "Понаблюдайте за автопилотом."}

    @staticmethod
    def _client_summary(health: str) -> dict[str, Any]:
        headline = {
            "healthy": "Автопилот работает штатно",
            "warning": "Есть предупреждения",
            "degraded": "Нужно вмешаться",
            "paused": "Автопилот на паузе",
            "blocked": "Публикация заблокирована",
            "failed": "Сбой автопилота",
            "unknown": "Пока нет данных",
        }.get(health, "Статус автопилота")
        tone = {
            "healthy": "ok",
            "warning": "warn",
            "degraded": "problem",
            "paused": "muted",
            "unknown": "muted",
        }.get(health, "muted")
        return {"headline": headline, "tone": tone}

    def _balance_snapshot(
        self, db: Session, account_id: int | None
    ) -> tuple[int | None, int | None]:
        if account_id is None:
            return None, None
        try:
            # ТОЛЬКО чтение: get_balance создаёт+коммитит счёт при отсутствии, что нарушило бы
            # инвариант «dry-run/preview ничего не пишет». Читаем без провизионирования.
            from app.repositories import billing_repository

            account = billing_repository.get_billing_account_by_account_id(db, account_id)
            if account is None:
                return None, None
            balance = int(account.balance_units)
            cost = max(
                1, int(self._billing_service().estimate_action_cost(USAGE_AUTO_PUBLISH_ACTION))
            )
            return balance, balance // cost
        except Exception:  # noqa: BLE001 - баланс не критичен для наблюдения
            return None, None

    def _transition_incident(
        self,
        db: Session,
        incident_id: int,
        repo_fn: Any,
        action: str,
        current_user_id: int | None,
    ) -> dict[str, Any]:
        incident = monitor_repo.get_incident_by_id(db, incident_id)
        if incident is None:
            raise LiveAutopilotMonitoringError("Инцидент не найден")
        updated = repo_fn(db, incident, current_user_id)
        self._write_audit(
            db,
            action,
            incident.account_id,
            incident.project_id,
            {"incident_id": incident_id, "incident_type": incident.incident_type},
        )
        return monitor_repo.public_incident_view(updated)

    def _record_incident_audit(
        self, db: Session, project: Any, incident: Any, created: bool
    ) -> None:
        if not created:
            return
        self._write_audit(
            db,
            audit_actions.ACTION_LIVE_MONITORING_INCIDENT_CREATED,
            project.account_id,
            project.id,
            {"incident_type": incident.incident_type, "severity": incident.severity},
        )

    # ------------------------------------------------------------------ #
    # Внутреннее: guard/подтверждения/scoping/ленивые сервисы            #
    # ------------------------------------------------------------------ #

    def _guard_kill_switch(self, settings: Settings) -> None:
        if not settings.live_autopilot_kill_switch_enabled_effective:
            raise LiveAutopilotMonitoringError("Стоп-кран отключён администратором.")

    def _require_pause_confirmation(self, confirmation: str | None, settings: Settings) -> None:
        if not settings.live_autopilot_kill_switch_require_confirmation:
            return
        expected = settings.live_autopilot_pause_confirmation_text_safe
        if str(confirmation or "").strip() != expected:
            raise LiveAutopilotMonitoringError(f"Требуется подтверждение: введите «{expected}»")

    def _require_resume_confirmation(self, confirmation: str | None, settings: Settings) -> None:
        if not settings.live_autopilot_kill_switch_require_confirmation:
            return
        expected = settings.live_autopilot_resume_confirmation_text_safe
        if str(confirmation or "").strip() != expected:
            raise LiveAutopilotMonitoringError(f"Требуется подтверждение: введите «{expected}»")

    def _require_project(self, db: Session, project_id: int) -> Any:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise LiveAutopilotMonitoringError("Проект не найден")
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

    def _autopilot_service(self) -> Any:
        if self._autopilot is None:
            from app.services.autopilot_service import AutopilotService

            self._autopilot = AutopilotService(settings=self._resolve_settings())
        return self._autopilot

    def _billing_service(self) -> Any:
        if self._billing is None:
            from app.services.billing_service import BillingService

            self._billing = BillingService(settings=self._resolve_settings())
        return self._billing

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
            entity_type="live_autopilot_monitoring",
            metadata=metadata or {},
        )


# --- Модульные помощники --- #

_HEALTH_LABELS: dict[str, str] = {
    "healthy": "Работает штатно",
    "warning": "Предупреждение",
    "degraded": "Требует внимания",
    "paused": "На паузе",
    "blocked": "Заблокировано",
    "failed": "Сбой",
    "unknown": "Нет данных",
}


class _soft:
    """Контекст «мягкого» вызова: побочная пауза/старт автопилота не роняет основное действие."""

    def __enter__(self) -> _soft:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if exc_type is not None:
            logger.warning("live-monitoring soft call failed: %s", exc_type.__name__)
        return True


def _blk(blocker_type: str, severity: str, message: str) -> dict[str, Any]:
    return {"type": blocker_type, "severity": severity, "message": message}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def get_live_autopilot_monitoring_service() -> LiveAutopilotMonitoringService:
    """DI-фабрика сервиса мониторинга автопилота."""
    return LiveAutopilotMonitoringService()
