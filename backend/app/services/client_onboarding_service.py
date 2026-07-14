"""Сервис клиентского онбординга — «запуск AI-автопилота за 5 минут» (v0.6.4).

Ведёт клиента по 5 шагам (бизнес → материалы → площадки → цель → запуск), а Botfleet сам создаёт
проект, autopilot-профиль, media-профиль, календарь, проверяет готовность и делает первый preview.

БЕЗОПАСНОСТЬ (инварианты):
- клиент НЕ видит worker/миграции/токены/live-флаги/готовность/биллинг;
- онбординг НЕ включает live-публикацию и НЕ трогает глобальные ``*_LIVE_PUBLISHING_ENABLED``:
  после завершения система READY, но LIVE=OFF (preview-first);
- секретов/токенов не сохраняет; всё под tenant isolation (проверка на API-слое).
"""

from __future__ import annotations

import re
import secrets
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import (
    account_repository,
    project_repository,
)
from app.repositories import (
    onboarding_repository as onb_repo,
)
from app.schemas.project import ProjectCreate
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

# Онбординг-цель → цель календаря (словарь календаря: sales/leads/reach/trust/expertise/mixed).
_GOAL_TO_CALENDAR: dict[str, str] = {
    "sales": "sales",
    "brand": "trust",
    "reach": "reach",
    "expertise": "expertise",
}
# Частота онбординга → preset календаря-ассистента.
_FREQ_TO_PRESET: dict[str, str] = {
    "daily": "daily",
    "3_week": "three_per_week",
    "weekly": "two_per_week",
}
# Частота → (frequency, weekdays) для CrmPublishingPlan (реальное расписание).
_FREQ_TO_SCHEDULE: dict[str, tuple[str, list[int]]] = {
    "daily": ("daily", []),
    "3_week": ("three_per_week", []),
    "weekly": ("custom", [0]),  # раз в неделю — понедельник
}


class ClientOnboardingError(Exception):
    """Ошибка онбординга (нет сессии/шага/данных) — API → 400/404."""


class ClientOnboardingService:
    """Пятишаговый мастер первого запуска автопилота (live не включает)."""

    def __init__(
        self,
        autopilot_service: Any | None = None,
        calendar_service: Any | None = None,
        yandex_sync_service: Any | None = None,
        platform_connection_service: Any | None = None,
        readiness_service: Any | None = None,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._autopilot = autopilot_service
        self._calendar = calendar_service
        self._yandex = yandex_sync_service
        self._platform_conn = platform_connection_service
        self._readiness = readiness_service
        self._audit = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Старт                                                              #
    # ------------------------------------------------------------------ #

    def start_onboarding(
        self, db: Session, user_id: int, company_name: str | None = None
    ) -> dict[str, Any]:
        """Начать онбординг: создать аккаунт/проект/autopilot-профиль + сессию (или активную)."""
        existing = onb_repo.get_active_session(db, user_id)
        if existing is not None:
            return {
                "session_id": existing.id,
                "project_id": existing.project_id,
                "current_step": existing.current_step,
                "progress": onb_repo.get_progress(existing),
                "resumed": True,
            }
        name = (company_name or "").strip() or "Мой бизнес"
        account = account_repository.create_account(
            db, name=name, slug=self._new_slug("acc"), owner_user_id=user_id
        )
        account_repository.create_membership(db, account.id, user_id, role="owner", status="active")
        project = self._create_project_unique_slug(db, name)
        project.account_id = account.id
        db.commit()
        db.refresh(project)
        # Autopilot-профиль (status=setup_required, is_enabled=False — live выключен).
        with _soft():
            self._autopilot_svc().get_or_create_profile(db, project.id, user_id)
        session = onb_repo.create_session(
            db, account_id=account.id, user_id=user_id, project_id=project.id
        )
        self._write_audit(
            db,
            audit_actions.ACTION_ONBOARDING_STARTED,
            account.id,
            project.id,
            {"session_id": session.id},
        )
        return {
            "session_id": session.id,
            "project_id": project.id,
            "current_step": 1,
            "progress": onb_repo.get_progress(session),
            "resumed": False,
        }

    # ------------------------------------------------------------------ #
    # Шаги                                                               #
    # ------------------------------------------------------------------ #

    def complete_business_step(
        self, db: Session, session_id: int, data: dict[str, Any], user_id: int | None = None
    ) -> dict[str, Any]:
        """Шаг 1 «Ваш бизнес»: сохранить контекст бизнеса + имя/описание проекта."""
        session = self._require_session(db, session_id, user_id)
        business = {
            "company_name": str(data.get("company_name") or "").strip(),
            "industry": str(data.get("industry") or "").strip(),
            "description": str(data.get("description") or "").strip(),
            "target_audience": str(data.get("target_audience") or "").strip(),
        }
        if not business["company_name"]:
            raise ClientOnboardingError("Укажите название компании")
        # Обновляем имя/описание проекта (без секретов).
        if session.project_id is not None:
            project = project_repository.get_project_by_id(db, session.project_id)
            if project is not None:
                project.name = business["company_name"]
                project.description = business["description"] or project.description
                db.commit()
        onb_repo.update_step(
            db,
            session,
            status="business_completed",
            current_step=2,
            data_field="business_data",
            data=business,
        )
        self._record_step(db, session, "business", business, {"saved": True})
        return self._step_response(db, session, "Материалы")

    def complete_media_step(
        self, db: Session, session_id: int, data: dict[str, Any], user_id: int | None = None
    ) -> dict[str, Any]:
        """Шаг 2 «Ваши материалы»: подключить Яндекс Диск (БЕЗ запуска синхронизации)."""
        session = self._require_session(db, session_id, user_id)
        url = str(data.get("yandex_disk_url") or "").strip()
        folder = str(data.get("folder") or "SMM").strip() or "SMM"
        if url and not self._looks_like_url(url):
            raise ClientOnboardingError("Похоже, ссылка на Яндекс Диск некорректна")
        profile_ok = True
        if url and session.project_id is not None:
            # Создаём media-профиль без сети (configure_profile НЕ запускает sync).
            with _soft() as soft_profile:
                self._yandex_svc().configure_profile(
                    db,
                    session.project_id,
                    {"public_url": url, "root_folder": folder},
                )
            profile_ok = soft_profile.ok
        media = {"yandex_disk_url": url, "folder": folder, "connected": bool(url) and profile_ok}
        onb_repo.update_step(
            db,
            session,
            status="media_completed",
            current_step=3,
            data_field="media_data",
            data=media,
        )
        self._record_step(db, session, "media", {"folder": folder, "has_url": bool(url)}, media)
        return self._step_response(db, session, "Площадки")

    def complete_platform_step(
        self, db: Session, session_id: int, data: dict[str, Any], user_id: int | None = None
    ) -> dict[str, Any]:
        """Шаг 3 «Где публиковать»: зарегистрировать площадки (live_enabled всегда OFF)."""
        session = self._require_session(db, session_id, user_id)
        selected = [p for p in ("telegram", "vk", "instagram") if bool(data.get(p))]
        if not selected:
            raise ClientOnboardingError("Выберите хотя бы одну площадку")
        connected: list[str] = []
        if session.project_id is not None:
            for platform in selected:
                payload = self._platform_payload(platform, data)
                with _soft():
                    self._platform_conn_svc().upsert_connection(
                        db, session.project_id, platform, payload
                    )
                    connected.append(platform)
        platform_data = {"selected": selected, "connected": connected}
        onb_repo.update_step(
            db,
            session,
            status="platforms_completed",
            current_step=4,
            data_field="platform_data",
            data=platform_data,
        )
        self._record_step(db, session, "platforms", {"selected": selected}, platform_data)
        return self._step_response(db, session, "Цель")

    def complete_goal_step(
        self, db: Session, session_id: int, data: dict[str, Any], user_id: int | None = None
    ) -> dict[str, Any]:
        """Шаг 4 «Что должен делать автопилот»: цель + частота → календарь (без публикаций)."""
        session = self._require_session(db, session_id, user_id)
        from app.models.onboarding_session import ONBOARDING_FREQUENCIES, ONBOARDING_GOALS

        goal = str(data.get("goal") or "").strip().lower()
        frequency = str(data.get("frequency") or "").strip().lower()
        if goal not in ONBOARDING_GOALS:
            raise ClientOnboardingError("Выберите цель автопилота")
        if frequency not in ONBOARDING_FREQUENCIES:
            frequency = "3_week"
        platforms = list(session.platform_data.get("selected") or ["telegram"])
        sched_freq, weekdays = _FREQ_TO_SCHEDULE.get(frequency, ("three_per_week", []))
        content_ok = calendar_ok = plan_ok = False
        if session.project_id is not None:
            # 1) Правила контента (цель).
            with _soft() as soft_content:
                self._autopilot_svc().configure_content_rules(
                    db, session.project_id, {"business_goal": goal}, user_id
                )
            content_ok = soft_content.ok
            # 2) Реальное расписание (CrmPublishingPlan) — на нём работает автопилот. Live НЕ вкл.
            with _soft() as soft_calendar:
                self._autopilot_svc().configure_calendar(
                    db,
                    session.project_id,
                    {"platforms": platforms, "frequency": sched_freq, "weekdays": weekdays},
                    user_id,
                )
            calendar_ok = soft_calendar.ok
            # 3) Клиентский план календаря-ассистента (AutopilotCalendarPlan).
            with _soft() as soft_plan:
                self._calendar_svc().create_calendar_plan(
                    db,
                    session.project_id,
                    {
                        "preset": _FREQ_TO_PRESET.get(frequency, "three_per_week"),
                        "goal": _GOAL_TO_CALENDAR.get(goal, "mixed"),
                        "platforms": platforms,
                    },
                    current_user_id=user_id,
                    dry_run=False,
                )
            plan_ok = soft_plan.ok
        # calendar_ready — реальный признак того, что расписание создано (для checklist финиша).
        goal_data = {
            "goal": goal,
            "frequency": frequency,
            "platforms": platforms,
            "calendar_ready": calendar_ok,
        }
        onb_repo.update_step(
            db,
            session,
            status="goal_completed",
            current_step=5,
            data_field="goal_data",
            data=goal_data,
        )
        self._record_step(
            db,
            session,
            "goal",
            {"goal": goal, "frequency": frequency},
            {
                "content_rules": content_ok,
                "calendar_created": calendar_ok,
                "assistant_plan": plan_ok,
            },
        )
        return self._step_response(db, session, "Запуск")

    def finish_onboarding(
        self, db: Session, session_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Шаг 5 «Запустите автопилот»: проверить готовность + сделать первый preview. LIVE=OFF."""
        session = self._require_session(db, session_id, user_id)
        if session.status not in ("goal_completed", "ready", "completed"):
            raise ClientOnboardingError(
                "Сначала пройдите все шаги: бизнес, материалы, площадки и цель"
            )
        # Порядок шагов не форсируется на каждом шаге, поэтому финиш требует, чтобы
        # ключевые шаги реально были пройдены (нельзя проскочить из старта сразу в цель).
        if not (
            session.business_data.get("company_name") and session.platform_data.get("selected")
        ):
            raise ClientOnboardingError(
                "Сначала пройдите все шаги: бизнес, материалы, площадки и цель"
            )
        readiness: dict[str, Any] = {"status": "unknown"}
        preview: dict[str, Any] = {}
        if session.project_id is not None:
            # Готовность — dry-run (ничего не пишет, live не включает).
            with _soft():
                check = self._readiness_svc().run_project_readiness_check(
                    db, session.project_id, dry_run=True
                )
                readiness = {
                    "status": check.get("status"),
                    "score": check.get("readiness_score"),
                    "checklist": {
                        k: bool(v.get("done")) for k, v in (check.get("checklist") or {}).items()
                    },
                }
            # Первый preview (needs_review draft; НЕ публикация, live не включается).
            with _soft():
                draft = self._autopilot_svc().create_first_draft_now(
                    db, session.project_id, None, user_id
                )
                preview = {
                    "created": bool(draft.get("post_id") or draft.get("created")),
                    "status": draft.get("status"),
                    "live_calls": bool(draft.get("live_calls")),
                }
        onb_repo.finish_session(db, session, status="ready")
        self._record_step(db, session, "finish", {}, {"readiness": readiness, "preview": preview})
        self._write_audit(
            db,
            audit_actions.ACTION_ONBOARDING_FINISHED,
            session.account_id,
            session.project_id,
            {"session_id": session.id},
        )
        return {
            "session_id": session.id,
            "project_id": session.project_id,
            "status": "ready",
            "live_enabled": False,  # ключевой инвариант: READY, но LIVE=OFF
            "readiness": readiness,
            "preview": preview,
            "next_action": "Создать первый пост",
            "checklist": {
                "materials": bool(session.media_data.get("connected")),
                # реальный признак создания расписания, а не только выбранной цели
                "calendar": bool(session.goal_data.get("calendar_ready")),
                "platforms": bool(session.platform_data.get("selected")),
                "ai_ready": bool(session.business_data.get("company_name")),
            },
            "note": (
                "Автопилот готов и настроен, но реальная публикация ВЫКЛЮЧЕНА. Проверьте первый "
                "пост и включите публикацию отдельно, когда будете готовы."
            ),
        }

    # ------------------------------------------------------------------ #
    # Чтение                                                             #
    # ------------------------------------------------------------------ #

    def get_session(
        self, db: Session, session_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Текущее состояние сессии онбординга (без секретов)."""
        session = self._require_session(db, session_id, user_id)
        return {
            **onb_repo.public_session_view(session),
            "steps": [
                onb_repo.public_result_view(r) for r in onb_repo.list_results(db, session.id)
            ],
            "progress": onb_repo.get_progress(session),
        }

    # ------------------------------------------------------------------ #
    # Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    def _step_response(self, db: Session, session: Any, next_step_label: str) -> dict[str, Any]:
        db.refresh(session)
        return {
            "session_id": session.id,
            "status": session.status,
            "current_step": session.current_step,
            "completion_percent": session.completion_percent,
            "next_step_label": next_step_label,
        }

    def _record_step(
        self,
        db: Session,
        session: Any,
        step_name: str,
        input_data: dict[str, Any],
        output_data: dict[str, Any],
    ) -> None:
        with _soft():
            onb_repo.save_result(
                db,
                session_id=session.id,
                step_name=step_name,
                status="completed",
                input_data=input_data,
                output_data=output_data,
            )
        self._write_audit(
            db,
            audit_actions.ACTION_ONBOARDING_STEP_COMPLETED,
            session.account_id,
            session.project_id,
            {"step": step_name},
        )

    @staticmethod
    def _platform_payload(platform: str, data: dict[str, Any]) -> dict[str, Any]:
        """Payload подключения площадки (креды опциональны; live всегда OFF)."""
        value = data.get(platform)
        payload: dict[str, Any] = {}
        if isinstance(value, dict):
            for key in ("api_key", "external_id", "url", "title"):
                if value.get(key):
                    payload[key] = str(value[key])
        return payload

    def _create_project_unique_slug(self, db: Session, name: str) -> Any:
        """Создать проект, переживая редкую коллизию слага (без orphan-аккаунта/500)."""
        from app.repositories.project_repository import SlugAlreadyExistsError

        last_exc: Exception | None = None
        for _ in range(5):
            try:
                return project_repository.create_project(
                    db, ProjectCreate(name=name, slug=self._new_slug("biz"))
                )
            except SlugAlreadyExistsError as exc:  # астрономически редко для token_hex(4)
                last_exc = exc
                db.rollback()
        raise ClientOnboardingError("Не удалось создать проект, попробуйте ещё раз") from last_exc

    @staticmethod
    def _new_slug(prefix: str) -> str:
        return f"{prefix}-{secrets.token_hex(4)}"

    @staticmethod
    def _looks_like_url(value: str) -> bool:
        return bool(re.match(r"^https?://", value.strip(), re.IGNORECASE))

    def _require_session(self, db: Session, session_id: int, user_id: int | None) -> Any:
        session = onb_repo.get_session_by_id(db, session_id)
        if session is None:
            raise ClientOnboardingError("Сессия онбординга не найдена")
        # Tenant isolation: сессия принадлежит пользователю (если user_id задан).
        # Fail-closed: если владелец сессии NULL, а вызов авторизован — доступ запрещён.
        if user_id is not None and session.user_id != user_id:
            raise ClientOnboardingError("Сессия онбординга не найдена")
        return session

    def _resolve_settings(self) -> Settings:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _autopilot_svc(self) -> Any:
        if self._autopilot is None:
            from app.services.autopilot_service import AutopilotService

            self._autopilot = AutopilotService(settings=self._resolve_settings())
        return self._autopilot

    def _calendar_svc(self) -> Any:
        if self._calendar is None:
            from app.services.autopilot_calendar_assistant_service import (
                AutopilotCalendarAssistantService,
            )

            self._calendar = AutopilotCalendarAssistantService(settings=self._resolve_settings())
        return self._calendar

    def _yandex_svc(self) -> Any:
        if self._yandex is None:
            from app.services.yandex_auto_sync_service import YandexAutoSyncService

            self._yandex = YandexAutoSyncService(settings=self._resolve_settings())
        return self._yandex

    def _platform_conn_svc(self) -> Any:
        if self._platform_conn is None:
            from app.services.platform_connection_service import PlatformConnectionService

            self._platform_conn = PlatformConnectionService()
        return self._platform_conn

    def _readiness_svc(self) -> Any:
        if self._readiness is None:
            from app.services.live_readiness_service import LiveReadinessService

            self._readiness = LiveReadinessService(settings=self._resolve_settings())
        return self._readiness

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
        project_id: int | None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._audit_svc().record(
            db,
            action,
            account_id=account_id,
            project_id=project_id,
            entity_type="onboarding_session",
            metadata=metadata or {},
        )


class _soft:
    """Контекст «мягкого» вызова: сбой оркестрации шага не роняет весь онбординг.

    Атрибут ``ok`` показывает, прошёл ли блок без исключения — чтобы записывать в результат
    шага реальный исход, а не хардкод-успех.
    """

    def __init__(self) -> None:
        self.ok = True

    def __enter__(self) -> _soft:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if exc_type is not None:
            self.ok = False
            logger.warning("onboarding soft call failed: %s", exc_type.__name__)
        return True


def get_client_onboarding_service() -> ClientOnboardingService:
    """DI-фабрика сервиса клиентского онбординга."""
    return ClientOnboardingService()
