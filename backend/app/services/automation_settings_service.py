"""Настройки режима автоматизации проекта/платформы/плана (v0.4.0).

Режим и safety-параметры авто-режима хранятся на :class:`CrmPublishingPlan`:
- ``automation_mode`` — semi_auto | full_auto;
- ``auto_publish_enabled`` — рубильник авто-публикации;
- ``learning_enabled`` — собирать ли сигналы обучения;
- ``require_review_before_first_auto`` — требовать одобрение до первой авто-публикации;
- ``min_quality_score_for_auto`` — порог качества для авто-режима.

ВАЖНО: включение full_auto НЕ означает live-публикацию — она всё равно проходит
через safety gates (live-флаг платформы, креды, баланс, порог качества). Переключение
на full_auto требует явного подтверждения ``ENABLE_FULL_AUTO``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.repositories import client_learning_repository, project_repository
from app.repositories import crm_bot_smm_repository as crm_repo
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:
    from app.models.crm_bot_smm import CrmPublishingPlan
    from app.services.audit_log_service import AuditLogService

AUTOMATION_MODES = ("semi_auto", "full_auto")
FULL_AUTO_CONFIRMATION = "ENABLE_FULL_AUTO"

# Поля, которые клиент может менять через настройки автоматизации.
_SETTABLE_FIELDS = (
    "automation_mode",
    "auto_publish_enabled",
    "learning_enabled",
    "require_review_before_first_auto",
    "min_quality_score_for_auto",
    "max_posts_per_day_auto",
)


class AutomationSettingsError(Exception):
    """Ошибка настроек автоматизации (нет подтверждения и т. п.) — API → 400."""


class AutomationPlanNotFoundError(AutomationSettingsError):
    """План публикаций не найден в проекте — API → 404 (ресурс пути)."""


class AutomationSettingsService:
    """Чтение/запись режима автоматизации на уровне проекта/платформы/плана."""

    def __init__(self, audit_service: AuditLogService | None = None) -> None:
        self._audit = audit_service

    # --- Чтение ---

    def get_project_settings(self, db: Session, project_id: int) -> dict[str, Any]:
        """Сводка режима автоматизации по всем планам проекта + готовность обучения."""
        plans = self._project_plans(db, project_id)
        plan_views = [self._plan_view(p) for p in plans]
        modes = {p["automation_mode"] for p in plan_views}
        effective_mode = (
            "full_auto"
            if modes == {"full_auto"}
            else ("mixed" if len(modes) > 1 else (next(iter(modes)) if modes else "semi_auto"))
        )
        profile = client_learning_repository.get_profile(db, project_id, None)
        return {
            "project_id": project_id,
            "effective_mode": effective_mode,
            "plans_count": len(plan_views),
            "plans": plan_views,
            "learning_profile_ready": profile is not None,
            "learning_confidence": round(profile.confidence_score, 3) if profile else 0.0,
            "learning_profile_version": profile.profile_version if profile else 0,
            "full_auto_confirmation_phrase": FULL_AUTO_CONFIRMATION,
        }

    def get_platform_settings(
        self, db: Session, project_id: int, platform_key: str
    ) -> dict[str, Any]:
        """Сводка режима по планам, включающим конкретную площадку."""
        plans = [
            p for p in self._project_plans(db, project_id) if platform_key in (p.platforms or [])
        ]
        return {
            "project_id": project_id,
            "platform_key": platform_key,
            "plans_count": len(plans),
            "plans": [self._plan_view(p) for p in plans],
        }

    # --- Запись ---

    def update_project_settings(
        self,
        db: Session,
        project_id: int,
        payload: dict[str, Any],
        user_id: int | None = None,
        confirm: str | None = None,
    ) -> dict[str, Any]:
        """Применить настройки автоматизации ко ВСЕМ планам проекта."""
        plans = self._project_plans(db, project_id)
        self._apply_to_plans(db, project_id, plans, payload, user_id, confirm)
        return self.get_project_settings(db, project_id)

    def update_platform_settings(
        self,
        db: Session,
        project_id: int,
        platform_key: str,
        payload: dict[str, Any],
        user_id: int | None = None,
        confirm: str | None = None,
    ) -> dict[str, Any]:
        """Применить настройки к планам проекта, включающим площадку."""
        plans = [
            p for p in self._project_plans(db, project_id) if platform_key in (p.platforms or [])
        ]
        self._apply_to_plans(db, project_id, plans, payload, user_id, confirm)
        return self.get_platform_settings(db, project_id, platform_key)

    def set_plan_mode(
        self,
        db: Session,
        project_id: int,
        plan_id: int,
        payload: dict[str, Any],
        user_id: int | None = None,
        confirm: str | None = None,
    ) -> dict[str, Any]:
        """Задать режим/параметры одного плана (с проверкой принадлежности проекту)."""
        plan = crm_repo.get_plan_by_id(db, plan_id)
        if plan is None or plan.project_id != project_id:
            raise AutomationPlanNotFoundError("План публикаций не найден в проекте")
        self._apply_to_plans(db, project_id, [plan], payload, user_id, confirm)
        db.refresh(plan)
        return {"project_id": project_id, "plan": self._plan_view(plan)}

    # --- Внутреннее ---

    def _apply_to_plans(
        self,
        db: Session,
        project_id: int,
        plans: list[CrmPublishingPlan],
        payload: dict[str, Any],
        user_id: int | None,
        confirm: str | None,
    ) -> None:
        """Провалидировать и записать поля автоматизации на набор планов."""
        clean = self._validate_payload(payload)
        target_mode = clean.get("automation_mode")
        enabling_full_auto = target_mode == "full_auto" or clean.get("auto_publish_enabled") is True
        if enabling_full_auto and confirm != FULL_AUTO_CONFIRMATION:
            raise AutomationSettingsError(
                "Для включения полностью автоматического режима введите подтверждение "
                f"'{FULL_AUTO_CONFIRMATION}'."
            )
        if not plans:
            raise AutomationSettingsError(
                "Нет планов публикаций для применения настроек. Создайте расписание."
            )
        account_id = self._account_id(db, project_id)
        for plan in plans:
            for field, value in clean.items():
                setattr(plan, field, value)
        db.commit()
        for plan in plans:
            db.refresh(plan)

        self._write_audit(
            db,
            account_id,
            project_id,
            user_id,
            audit_actions.ACTION_AUTOMATION_MODE_CHANGED,
            {"plans": [p.id for p in plans], "changes": clean},
        )
        if enabling_full_auto:
            self._write_audit(
                db,
                account_id,
                project_id,
                user_id,
                audit_actions.ACTION_AUTOMATION_FULL_AUTO_ENABLED,
                {"plans": [p.id for p in plans]},
            )
        elif target_mode == "semi_auto":
            self._write_audit(
                db,
                account_id,
                project_id,
                user_id,
                audit_actions.ACTION_AUTOMATION_FULL_AUTO_DISABLED,
                {"plans": [p.id for p in plans]},
            )

    @staticmethod
    def _validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
        """Отфильтровать разрешённые поля и провалидировать значения."""
        clean: dict[str, Any] = {}
        for field in _SETTABLE_FIELDS:
            if field not in payload or payload[field] is None:
                continue
            value = payload[field]
            if field == "automation_mode" and value not in AUTOMATION_MODES:
                raise AutomationSettingsError(
                    f"Недопустимый режим: '{value}'. Ожидается semi_auto|full_auto."
                )
            if field == "min_quality_score_for_auto":
                value = max(0, min(100, int(value)))
            if field == "max_posts_per_day_auto":
                value = max(0, int(value))
            clean[field] = value
        # semi_auto всегда выключает авто-публикацию.
        if clean.get("automation_mode") == "semi_auto":
            clean["auto_publish_enabled"] = False
        return clean

    def _project_plans(self, db: Session, project_id: int) -> list[CrmPublishingPlan]:
        config = crm_repo.get_config_by_project_id(db, project_id)
        if config is None:
            return []
        return crm_repo.list_plans_by_config(db, config.id)

    @staticmethod
    def _plan_view(plan: CrmPublishingPlan) -> dict[str, Any]:
        return {
            "plan_id": plan.id,
            "category_id": plan.category_id,
            "platforms": list(plan.platforms or []),
            "is_active": plan.is_active,
            "automation_mode": plan.automation_mode,
            "auto_publish_enabled": plan.auto_publish_enabled,
            "learning_enabled": plan.learning_enabled,
            "require_review_before_first_auto": plan.require_review_before_first_auto,
            "min_quality_score_for_auto": plan.min_quality_score_for_auto,
            "max_posts_per_day_auto": plan.max_posts_per_day_auto,
            "safety_notes": list(plan.safety_notes or []),
        }

    @staticmethod
    def _account_id(db: Session, project_id: int) -> int | None:
        project = project_repository.get_project_by_id(db, project_id)
        return project.account_id if project is not None else None

    def _write_audit(
        self,
        db: Session,
        account_id: int | None,
        project_id: int,
        user_id: int | None,
        action: str,
        metadata: dict[str, Any],
    ) -> None:
        self._audit_svc().record(
            db,
            action,
            account_id=account_id,
            user_id=user_id,
            project_id=project_id,
            entity_type="publishing_plan",
            metadata=metadata,
        )

    def _audit_svc(self) -> AuditLogService:
        if self._audit is None:
            from app.services.audit_log_service import AuditLogService

            self._audit = AuditLogService()
        return self._audit


def get_automation_settings_service() -> AutomationSettingsService:
    """DI-фабрика сервиса настроек автоматизации."""
    return AutomationSettingsService()
