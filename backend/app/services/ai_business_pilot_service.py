"""AIBusinessPilotService — окружение реального бизнес-пилота (v0.9.1).

Готовит пилот реальной компании: создаёт pilot-воркспейс и бизнес-профиль, считает health бизнеса
из уже собранных данных смежных слоёв (Performance / Operations / Forecasting) — ТОЛЬКО чтение.

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- работает только при pilot_mode=true (иначе PilotModeDisabledError → 403);
- всё advisory: НЕ меняет бизнес/CRM, НЕ выполняет workflow, НЕ шлёт сообщений, НЕ ходит во внешние
  API; НЕ создаёт платежей; health — READ-ONLY чтение персистов в try/except;
- создание воркспейса — ТОЛЬКО участнику аккаунта (FAIL CLOSED: сбой проверки → отказ);
- строго per-account; секретов нет; бесплатно (0 units);
- изменения (workspace_created / profile_created) → AuditLog.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import pilot_repository as repo
from app.repositories import project_repository
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.pilot_workspace import PilotWorkspace
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)


def pilot_project_slug(workspace_id: int) -> str:
    """Детерминированный slug изолированного pilot-проекта для воркспейса."""
    return f"pilot-ws-{workspace_id}"


def resolve_pilot_project(db: Session, workspace: PilotWorkspace) -> Any:
    """Резолвить pilot-проект воркспейса ТОЛЬКО если он принадлежит тому же аккаунту.

    Slug глобально уникален — при совпадении slug с проектом ЧУЖОГО аккаунта возвращаем None
    (не читаем/не пишем в чужой проект → нет cross-tenant утечки бизнес-профиля).
    """
    project = project_repository.get_project_by_slug(db, pilot_project_slug(workspace.id))
    if project is None:
        return None
    if project.account_id != workspace.account_id:
        return None
    return project


class PilotModeDisabledError(Exception):
    """PILOT-режим выключен — API → 403."""


class AIBusinessPilotError(Exception):
    """Ошибка pilot-слоя (нет воркспейса/аккаунта; владелец без доступа) — API → 400/404."""


class AIBusinessPilotService:
    """Pilot-окружение: workspace → business profile → business health."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Workspace / profile                                               #
    # ------------------------------------------------------------------ #

    def create_pilot_workspace(
        self,
        db: Session,
        account_id: int,
        *,
        company_name: str,
        industry: str = "",
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Создать pilot-воркспейс (pilot_mode + аккаунт существует + пользователь участник)."""
        self._require_pilot_mode()
        if account_id is None:
            raise AIBusinessPilotError("account_id обязателен")
        self._require_account_member(db, account_id, user_id)
        workspace = repo.create_workspace(
            db,
            account_id=account_id,
            company_name=company_name,
            industry=industry,
            status="active",
            created_by=user_id,
        )
        self._write_audit(
            db,
            audit_actions.ACTION_PILOT_WORKSPACE_CREATED,
            account_id,
            user_id,
            workspace.id,
            {"company_name": company_name},
            entity_type="pilot_workspace",
        )
        return repo.public_workspace_view(workspace)

    def create_business_profile(
        self,
        db: Session,
        workspace_id: int,
        *,
        products: list[Any] | None = None,
        services: list[Any] | None = None,
        team: dict[str, Any] | None = None,
        sales_channels: list[Any] | None = None,
        business_description: str | None = None,
        current_revenue: float = 0.0,
        target_revenue: float = 0.0,
        kpi: dict[str, Any] | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Создать бизнес-профиль пилота."""
        self._require_pilot_mode()
        workspace = self._require_workspace(db, workspace_id)
        profile = repo.create_profile(
            db,
            workspace_id=workspace.id,
            products=products,
            services=services,
            team=team,
            sales_channels=sales_channels,
            business_description=business_description,
            current_revenue=current_revenue,
            target_revenue=target_revenue,
            kpi=kpi,
        )
        self._write_audit(
            db,
            audit_actions.ACTION_PILOT_PROFILE_CREATED,
            workspace.account_id,
            user_id,
            profile.id,
            {"current_revenue": current_revenue, "target_revenue": target_revenue},
            entity_type="pilot_business_profile",
        )
        return repo.public_profile_view(profile)

    def get_workspace(self, db: Session, workspace_id: int) -> dict[str, Any]:
        """Pilot-воркспейс + профиль (если есть)."""
        self._require_pilot_mode()
        workspace = self._require_workspace(db, workspace_id)
        profile = repo.get_profile(db, workspace.id)
        return {
            "workspace": repo.public_workspace_view(workspace),
            "profile": repo.public_profile_view(profile) if profile is not None else None,
        }

    def list_workspaces(self, db: Session, account_id: int | None = None) -> list[dict[str, Any]]:
        """Pilot-воркспейсы аккаунта."""
        self._require_pilot_mode()
        return [
            repo.public_workspace_view(w) for w in repo.list_workspaces(db, account_id=account_id)
        ]

    # ------------------------------------------------------------------ #
    # Business health (read-only)                                       #
    # ------------------------------------------------------------------ #

    def get_business_health(self, db: Session, workspace_id: int) -> dict[str, Any]:
        """Здоровье бизнеса из Performance / Operations / Forecasting (ТОЛЬКО чтение)."""
        self._require_pilot_mode()
        workspace = self._require_workspace(db, workspace_id)
        project = resolve_pilot_project(db, workspace)
        if project is None:
            return {"score": 0.0, "risks": [], "opportunities": [], "has_data": False}
        pid = project.id
        risks: list[str] = []
        opportunities: list[str] = []
        perf_score: float | None = None
        ops_score: float | None = None

        # Performance Intelligence (read-only).
        try:
            from app.repositories import performance_repository as perf_repo

            snapshot = perf_repo.get_latest_snapshot(db, pid)
            if snapshot is not None:
                perf_score = float(snapshot.performance_score or 0.0)
                risks.extend(
                    d.title
                    for d in perf_repo.list_deviations(db, snapshot.id)
                    if d.impact in ("high", "critical")
                )
                opportunities.extend(
                    r.title for r in perf_repo.list_recommendations(db, snapshot.id)
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("pilot health performance failed: %s", type(exc).__name__)

        # Operations Control (read-only).
        try:
            from app.repositories import operations_repository as ops_repo

            ops = ops_repo.get_latest_snapshot(db, pid)
            if ops is not None:
                ops_score = float(ops.health_score or 0.0)
            risks.extend(
                risk.title
                for risk in ops_repo.list_risks(db, pid, status="open")
                if risk.severity in ("high", "critical")
            )
            opportunities.extend(rec.title for rec in ops_repo.list_recommendations(db, pid))
        except Exception as exc:  # noqa: BLE001
            logger.warning("pilot health operations failed: %s", type(exc).__name__)

        # Business Forecasting (read-only).
        try:
            from app.repositories import business_forecast_repository as fc_repo

            forecast = fc_repo.get_latest_forecast(db, pid)
            if forecast is not None:
                if forecast.risk_level in ("high", "critical"):
                    risks.append(f"Прогноз: повышенный риск ({forecast.risk_level})")
                confidence = round(float(forecast.confidence_score or 0.0), 0)
                opportunities.append(
                    f"Прогноз построен (уверенность {confidence:.0f}%) — цель достижима при фокусе"
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("pilot health forecast failed: %s", type(exc).__name__)

        scores = [s for s in (perf_score, ops_score) if s is not None]
        score = round(sum(scores) / len(scores), 1) if scores else 0.0
        return {
            "score": score,
            "risks": risks[:10],
            "opportunities": opportunities[:10],
            "has_data": True,
        }

    # ------------------------------------------------------------------ #
    # Внутреннее                                                         #
    # ------------------------------------------------------------------ #

    def _require_pilot_mode(self) -> None:
        if not self._resolve_settings().pilot_mode_effective:
            raise PilotModeDisabledError("PILOT-режим выключен (pilot_mode=false)")

    def _require_workspace(self, db: Session, workspace_id: int) -> PilotWorkspace:
        workspace = repo.get_workspace(db, workspace_id)
        if workspace is None:
            raise AIBusinessPilotError("Pilot-воркспейс не найден")
        return workspace

    def _require_account_member(self, db: Session, account_id: int, user_id: int | None) -> None:
        """Пользователь должен иметь доступ к аккаунту (FAIL CLOSED: сбой проверки → отказ)."""
        from app.repositories import account_repository, user_repository
        from app.services import saas_security_service as security

        if account_repository.get_account_by_id(db, account_id) is None:
            raise AIBusinessPilotError(f"Аккаунт id={account_id} не найден")
        if user_id is None:
            raise AIBusinessPilotError("Требуется пользователь-участник аккаунта")
        try:
            user = user_repository.get_user_by_id(db, user_id)
            allowed = user is not None and security.user_can_access_account(db, user, account_id)
        except Exception as exc:  # noqa: BLE001 — сбой проверки доступа → fail closed
            logger.warning("pilot account member check failed: %s", type(exc).__name__)
            raise AIBusinessPilotError("Не удалось проверить доступ пользователя") from exc
        if not allowed:
            raise AIBusinessPilotError("Пользователь не имеет доступа к аккаунту")

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
        metadata: dict[str, Any],
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
            metadata=metadata,
        )


def get_ai_business_pilot_service() -> AIBusinessPilotService:
    """DI-фабрика AI Business Pilot."""
    return AIBusinessPilotService()
