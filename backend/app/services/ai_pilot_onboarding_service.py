"""AIPilotOnboardingService — онбординг реальной компании в пилот (v1.0.0).

Заводит пилот компании одним шагом: PilotWorkspace → PilotBusinessProfile → PilotGoal → PilotKPI.
Только создание описательных сущностей пилота — AI ничего не выполняет и бизнес не меняет.

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- работает только при pilot_mode=true; воркспейс — ТОЛЬКО участнику аккаунта (fail-closed);
- НЕ выполняет рекомендаций, НЕ меняет бизнес/CRM/финансы, НЕ шлёт сообщений, НЕ создаёт платежей;
- секретов нет; бесплатно (0 units); изменения (workspace/profile/goal/kpi_created) → AuditLog.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.models.pilot_goal import PILOT_GOAL_STATUSES, PILOT_PRIORITIES
from app.models.pilot_kpi import PILOT_KPI_FREQUENCIES, PILOT_KPI_STATUSES
from app.repositories import pilot_repository as repo
from app.services import audit_log_service as audit_actions
from app.services.ai_business_pilot_service import (
    AIBusinessPilotError,
    AIBusinessPilotService,
    PilotModeDisabledError,
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

# Дефолтный пилот TEEON (используется если параметры онбординга не заданы).
_DEFAULT_GOAL: dict[str, Any] = {
    "title": "Увеличить выручку с 5 млн до 10 млн",
    "current_value": 5_000_000.0,
    "target_value": 10_000_000.0,
    "unit": "руб/мес",
    "priority": "high",
}
_DEFAULT_KPIS: list[dict[str, Any]] = [
    {"name": "Конверсия в продажу", "current_value": 2.0, "target_value": 4.0, "unit": "%"},
    {"name": "Средний чек", "current_value": 2500.0, "target_value": 3500.0, "unit": "руб"},
]


def _to_float(value: Any, field: str) -> float:
    """Привести значение к float; невалидный ввод → AIBusinessPilotError (API → 400, не 500)."""
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise AIBusinessPilotError(f"Поле «{field}» должно быть числом") from exc


def _enum(value: Any, allowed: tuple[str, ...], default: str, field: str) -> str:
    """Проверить значение по whitelist enum (пусто → default; чужое → AIBusinessPilotError/400)."""
    if value is None or value == "":
        return default
    text = str(value)
    if text not in allowed:
        raise AIBusinessPilotError(f"Недопустимое значение поля «{field}»: {text}")
    return text


def _require_dict(value: Any, field: str) -> dict[str, Any]:
    """Гарантировать, что значение — dict (иначе AIBusinessPilotError/400, не 500)."""
    if not isinstance(value, dict):
        raise AIBusinessPilotError(f"Поле «{field}» должно быть объектом")
    return value


def _normalize_goal(spec: dict[str, Any]) -> dict[str, Any]:
    """Валидировать/нормализовать спецификацию цели ДО записи в БД (fail fast → 400)."""
    spec = _require_dict(spec, "goal")
    return {
        "title": str(spec.get("title") or "Бизнес-цель"),
        "description": spec.get("description"),
        "current_value": _to_float(spec.get("current_value"), "current_value"),
        "target_value": _to_float(spec.get("target_value"), "target_value"),
        "unit": str(spec.get("unit") or ""),
        "priority": _enum(spec.get("priority"), PILOT_PRIORITIES, "medium", "priority"),
        "status": _enum(spec.get("status"), PILOT_GOAL_STATUSES, "active", "status"),
    }


def _normalize_kpi(spec: dict[str, Any]) -> dict[str, Any]:
    """Валидировать/нормализовать спецификацию KPI ДО записи в БД (fail fast → 400)."""
    spec = _require_dict(spec, "kpi")
    return {
        "name": str(spec.get("name") or "KPI"),
        "current_value": _to_float(spec.get("current_value"), "current_value"),
        "target_value": _to_float(spec.get("target_value"), "target_value"),
        "unit": str(spec.get("unit") or ""),
        "frequency": _enum(spec.get("frequency"), PILOT_KPI_FREQUENCIES, "monthly", "frequency"),
        "status": _enum(spec.get("status"), PILOT_KPI_STATUSES, "active", "status"),
    }


class AIPilotOnboardingService:
    """Онбординг компании: workspace → profile → goal → KPI."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings

    def create_company_pilot(
        self,
        db: Session,
        account_id: int,
        *,
        company_name: str = "TEEON Pilot",
        industry: str = "apparel",
        profile: dict[str, Any] | None = None,
        goals: list[dict[str, Any]] | None = None,
        kpis: list[dict[str, Any]] | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Завести пилот компании: workspace → profile → goal(s) → KPI(s)."""
        self._require_pilot_mode()
        # Валидируем ВЕСЬ ввод ДО первой записи в БД: невалидные числа/enum → 400, а не 500
        # после частично созданного пилота (workspace/profile/goal остались бы «сиротами»).
        profile_data = _require_dict(profile, "profile") if profile else {}
        current_revenue = _to_float(
            profile_data.get("current_revenue") or _DEFAULT_GOAL["current_value"], "current_revenue"
        )
        target_revenue = _to_float(
            profile_data.get("target_revenue") or _DEFAULT_GOAL["target_value"], "target_revenue"
        )
        goal_specs = [_normalize_goal(s) for s in (goals if goals is not None else [_DEFAULT_GOAL])]
        kpi_specs = [_normalize_kpi(s) for s in (kpis if kpis is not None else _DEFAULT_KPIS)]

        pilot = AIBusinessPilotService(
            audit_service=self._audit_svc, settings=self._resolve_settings()
        )
        # workspace (проверка pilot_mode + аккаунт + участник; audit workspace_created).
        workspace = pilot.create_pilot_workspace(
            db, account_id, company_name=company_name, industry=industry, user_id=user_id
        )
        wid = workspace["id"]
        # business profile (audit profile_created).
        profile_view = pilot.create_business_profile(
            db,
            wid,
            products=profile_data.get("products"),
            services=profile_data.get("services"),
            team=profile_data.get("team"),
            sales_channels=profile_data.get("sales_channels"),
            business_description=profile_data.get("business_description"),
            current_revenue=current_revenue,
            target_revenue=target_revenue,
            kpi=profile_data.get("kpi"),
            user_id=user_id,
        )
        goal_views = [self._create_goal(db, workspace, spec, user_id) for spec in goal_specs]
        kpi_views = [self._create_kpi(db, workspace, spec, user_id) for spec in kpi_specs]

        return {
            "workspace": workspace,
            "profile": profile_view,
            "goals": goal_views,
            "kpis": kpi_views,
        }

    def create_goal(
        self, db: Session, workspace_id: int, spec: dict[str, Any], user_id: int | None = None
    ) -> dict[str, Any]:
        """Создать одну бизнес-цель пилота."""
        self._require_pilot_mode()
        normalized = _normalize_goal(spec)
        workspace = self._require_workspace(db, workspace_id)
        return self._create_goal(db, repo.public_workspace_view(workspace), normalized, user_id)

    def create_kpi(
        self, db: Session, workspace_id: int, spec: dict[str, Any], user_id: int | None = None
    ) -> dict[str, Any]:
        """Создать один KPI пилота."""
        self._require_pilot_mode()
        normalized = _normalize_kpi(spec)
        workspace = self._require_workspace(db, workspace_id)
        return self._create_kpi(db, repo.public_workspace_view(workspace), normalized, user_id)

    # ------------------------------------------------------------------ #
    # Внутреннее                                                         #
    # ------------------------------------------------------------------ #

    def _create_goal(
        self, db: Session, workspace: dict[str, Any], spec: dict[str, Any], user_id: int | None
    ) -> dict[str, Any]:
        """Записать нормализованную цель (spec уже провалидирован _normalize_goal)."""
        goal = repo.create_goal(
            db,
            workspace_id=workspace["id"],
            title=spec["title"],
            description=spec["description"],
            current_value=spec["current_value"],
            target_value=spec["target_value"],
            unit=spec["unit"],
            priority=spec["priority"],
            status=spec["status"],
        )
        self._write_audit(
            db,
            audit_actions.ACTION_PILOT_GOAL_CREATED,
            workspace.get("account_id"),
            user_id,
            goal.id,
            entity_type="pilot_goal",
        )
        return repo.public_goal_view(goal)

    def _create_kpi(
        self, db: Session, workspace: dict[str, Any], spec: dict[str, Any], user_id: int | None
    ) -> dict[str, Any]:
        """Записать нормализованный KPI (spec уже провалидирован _normalize_kpi)."""
        kpi = repo.create_kpi(
            db,
            workspace_id=workspace["id"],
            name=spec["name"],
            current_value=spec["current_value"],
            target_value=spec["target_value"],
            unit=spec["unit"],
            frequency=spec["frequency"],
            status=spec["status"],
        )
        self._write_audit(
            db,
            audit_actions.ACTION_PILOT_KPI_CREATED,
            workspace.get("account_id"),
            user_id,
            kpi.id,
            entity_type="pilot_kpi",
        )
        return repo.public_kpi_view(kpi)

    def _require_pilot_mode(self) -> None:
        if not self._resolve_settings().pilot_mode_effective:
            raise PilotModeDisabledError("PILOT-режим выключен (pilot_mode=false)")

    def _require_workspace(self, db: Session, workspace_id: int) -> Any:
        workspace = repo.get_workspace(db, workspace_id)
        if workspace is None:
            raise AIBusinessPilotError("Pilot-воркспейс не найден")
        return workspace

    def _resolve_settings(self) -> Settings:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _write_audit(
        self,
        db: Session,
        action: str,
        account_id: int | None,
        user_id: int | None,
        entity_id: int | None,
        entity_type: str = "pilot_workspace",
    ) -> None:
        if self._audit_svc is None:
            from app.services.audit_log_service import AuditLogService

            self._audit_svc = AuditLogService(self._resolve_settings())
        self._audit_svc.record(
            db,
            action,
            account_id=account_id,
            user_id=user_id,
            project_id=None,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata={},
        )


def get_ai_pilot_onboarding_service() -> AIPilotOnboardingService:
    """DI-фабрика AI Pilot Onboarding."""
    return AIPilotOnboardingService()
