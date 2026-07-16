"""AIBusinessOSDemoService — demo-данные для MVP Testing Framework (v0.9.0).

Готовит тестовое окружение для E2E-прогонов всей AI-цепочки: создаёт demo-воркспейс (компанию),
описывает demo-цель и заводит demo-сценарии. Только demo-данные тестового режима.

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- работает только при demo_mode=true; НЕ создаёт реальных пользователей/CRM/платежей;
- НЕ выполняет внешних действий; НЕ отправляет сообщений; секретов нет; бесплатно (0 units);
- изменения (workspace_created) → AuditLog.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import demo_testing_repository as repo
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.demo_workspace import DemoWorkspace
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

# Профиль demo-компании TEEON (используется как вход для сценариев).
DEMO_COMPANY_PROFILE: dict[str, Any] = {
    "company_name": "TEEON Demo",
    "industry": "apparel",
    "employees": 25,
    "monthly_revenue": 5_000_000,
    "growth_target": 10_000_000,
}


class AIBusinessOSDemoError(Exception):
    """Ошибка demo-слоя (demo-режим выключен / нет воркспейса) — API → 400/404."""


class AIBusinessOSDemoService:
    """Подготовка demo-данных: компания → цель → сценарии."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Demo-данные                                                        #
    # ------------------------------------------------------------------ #

    def create_demo_company(
        self,
        db: Session,
        account_id: int | None,
        *,
        name: str = "TEEON Demo",
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Создать demo-воркспейс TEEON (apparel, 25 сотр., выручка 5М→10М)."""
        self._require_demo_mode()
        workspace = repo.create_workspace(
            db,
            account_id=account_id,
            name=name,
            company_name=DEMO_COMPANY_PROFILE["company_name"],
            industry=DEMO_COMPANY_PROFILE["industry"],
            description=(
                f"Demo-компания E2E: {DEMO_COMPANY_PROFILE['employees']} сотрудников, "
                f"выручка {DEMO_COMPANY_PROFILE['monthly_revenue']} → "
                f"{DEMO_COMPANY_PROFILE['growth_target']}."
            ),
        )
        self._write_audit(
            db,
            audit_actions.ACTION_DEMO_WORKSPACE_CREATED,
            account_id,
            user_id,
            workspace.id,
            {"company": DEMO_COMPANY_PROFILE["company_name"]},
        )
        return repo.public_workspace_view(workspace)

    def create_demo_goal(self) -> dict[str, Any]:
        """Спецификация demo-цели: выручка 5М → 10М за 12 месяцев (используется сценариями)."""
        return {
            "goal_type": "revenue",
            "title": "Увеличить выручку с 5 млн до 10 млн",
            "current_value": float(DEMO_COMPANY_PROFILE["monthly_revenue"]),
            "target_value": float(DEMO_COMPANY_PROFILE["growth_target"]),
            "horizon_months": 12,
        }

    def create_demo_scenario(
        self, db: Session, workspace_id: int, scenario_type: str, *, user_id: int | None = None
    ) -> dict[str, Any]:
        """Завести demo-сценарий (draft) для воркспейса."""
        self._require_demo_mode()
        from app.models.demo_scenario import SCENARIO_TYPES

        if scenario_type not in SCENARIO_TYPES:
            raise AIBusinessOSDemoError(f"Неизвестный тип сценария: {scenario_type}")
        workspace = self._require_workspace(db, workspace_id)
        scenario = repo.create_scenario(
            db,
            workspace_id=workspace.id,
            scenario_type=scenario_type,
            status="draft",
            input_data={"scenario_type": scenario_type, "company": DEMO_COMPANY_PROFILE},
        )
        return repo.public_scenario_view(scenario)

    def get_workspace(self, db: Session, workspace_id: int) -> dict[str, Any]:
        """Demo-воркспейс + профиль компании."""
        workspace = self._require_workspace(db, workspace_id)
        return {
            "workspace": repo.public_workspace_view(workspace),
            "profile": DEMO_COMPANY_PROFILE,
            "goal": self.create_demo_goal(),
        }

    def list_workspaces(self, db: Session, account_id: int | None = None) -> list[dict[str, Any]]:
        """Demo-воркспейсы (опционально по аккаунту)."""
        return [
            repo.public_workspace_view(w) for w in repo.list_workspaces(db, account_id=account_id)
        ]

    # ------------------------------------------------------------------ #
    # Внутреннее                                                         #
    # ------------------------------------------------------------------ #

    def _require_demo_mode(self) -> None:
        if not self._resolve_settings().demo_mode_effective:
            raise AIBusinessOSDemoError("DEMO-режим выключен (demo_mode=false)")

    def _require_workspace(self, db: Session, workspace_id: int) -> DemoWorkspace:
        workspace = repo.get_workspace(db, workspace_id)
        if workspace is None:
            raise AIBusinessOSDemoError("Demo-воркспейс не найден")
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
        metadata: dict[str, Any],
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
            entity_type="demo_workspace",
            entity_id=entity_id,
            metadata=metadata,
        )


def get_ai_business_os_demo_service() -> AIBusinessOSDemoService:
    """DI-фабрика AI Business OS Demo."""
    return AIBusinessOSDemoService()
